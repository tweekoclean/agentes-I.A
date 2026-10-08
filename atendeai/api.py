from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timedelta
import logging
import secrets
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import APIKeyHeader
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from .catalog import CITIES, SEGMENTS, resolve_city
from .commercial import CommercialError, CommercialService
from .commercial_routes import commercial_routers
from .config import Settings
from .local_ai import local_ai_status
from .local_ai_runtime import LocalAIRuntime, cpu_limit_cores, memory_limit_mb
from .support import SupportService
from .support_routes import support_routers
from .database_ssl import DatabaseSSL
from .models import Base, ConsentEvent, Lead, as_utc, build_database, utcnow
from .panel_routes import panel_router
from .research import AnalysisError, analyze
from .service import run_search, serialize_lead
from .sources import DemoSource, OverpassSource, SourceBusy, SourceError, normalize_phone


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchRequest(StrictBody):
    cidade: str = Field(default="Campinas", min_length=2, max_length=100)
    segmentos: list[str] = Field(default_factory=lambda: ["restaurantes", "lojas", "oficinas"], min_length=1, max_length=7)
    limite: int = Field(default=100, ge=1, le=1000)
    usar_cache: bool = True

    @field_validator("cidade")
    @classmethod
    def valid_city(cls, value):
        return resolve_city(value).name

    @field_validator("segmentos")
    @classmethod
    def valid_segments(cls, values):
        if any(name not in SEGMENTS for name in values):
            raise ValueError("Segmento não suportado. Consulte /v1/segmentos.")
        return sorted(set(values))


class ReviewRequest(StrictBody):
    status: Literal["pendente", "aprovada", "descartada"]
    observacao: str = Field(default="", max_length=2000)


class ConsentRequest(StrictBody):
    status: Literal["concedido", "revogado"]
    destinatario_whatsapp: str = Field(min_length=10, max_length=30)
    evidencia: str = Field(min_length=20, max_length=4000,
                           description="Registro verificável da autorização ou revogação; não usar apenas a URL do telefone público.")
    ocorrido_em: datetime = Field(default_factory=utcnow)

    @field_validator("destinatario_whatsapp")
    @classmethod
    def valid_phone(cls, value):
        phone = normalize_phone(value)
        if not phone:
            raise ValueError("Informe um único telefone brasileiro com DDD, de preferência no formato +55...")
        return phone

    @field_validator("ocorrido_em")
    @classmethod
    def valid_timestamp(cls, value):
        if value.tzinfo is None:
            raise ValueError("Informe a data com fuso horário, por exemplo -03:00.")
        if value > utcnow() + timedelta(minutes=5):
            raise ValueError("A autorização não pode estar no futuro.")
        return value


def create_app(settings=None, source=None, ai_transport=None, whatsapp_transport=None):
    settings = settings or Settings.from_env()
    database_url = settings.validated()
    ssl_files = DatabaseSSL(settings, database_url)
    try:
        engine, sessions = build_database(database_url, connect_args=ssl_files.connect_args)
    except Exception:
        ssl_files.close()
        raise
    source = source or (DemoSource() if settings.search_provider == "demo" else OverpassSource(settings.overpass_url))
    commercial = CommercialService(sessions, settings, whatsapp_transport, ai_transport)
    support = SupportService(sessions, settings, whatsapp_transport, ai_transport)
    runtime = LocalAIRuntime(settings)

    async def background_worker(stop, service):
        while not stop.is_set():
            try:
                await asyncio.to_thread(service.process_cycle)
            except Exception as error:
                # Não registra payload, token ou dados privados na mensagem de erro.
                logging.getLogger("atendeai.fila").error("Falha no processamento de %s: %s", type(service).__name__, type(error).__name__)
            try:
                await asyncio.wait_for(stop.wait(), timeout=3)
            except TimeoutError:
                pass

    @asynccontextmanager
    async def lifespan(app):
        tasks, stop = [], asyncio.Event()
        try:
            Base.metadata.create_all(engine)
            if settings.support_demo_enabled and settings.environment != "test":
                support.ensure_demo()
            if settings.local_ai_autostart and settings.environment != "test":
                tasks.append(asyncio.create_task(runtime.run()))
            if settings.whatsapp_ready and settings.environment != "test":
                tasks.append(asyncio.create_task(background_worker(stop, commercial)))
            if settings.environment != "test":
                tasks.append(asyncio.create_task(background_worker(stop, support)))
            yield
        finally:
            stop.set()
            runtime.request_stop()
            try:
                if tasks:
                    await asyncio.gather(*tasks)
            finally:
                engine.dispose()
                ssl_files.close()

    app = FastAPI(title="AtendeAI — Pesquisa, Comercial e Atendimento", version="0.5.2", lifespan=lifespan,
                  description="Pesquisa em São Paulo, conversa comercial e suporte por empresa via site e WhatsApp oficial. O painel está em /painel. Use Authorize com ADMIN_API_KEY nas rotas administrativas; visitantes usam tokens próprios.")
    app.state.settings, app.state.engine, app.state.sessions = settings, engine, sessions
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type", "X-Site-Key"])
    app.state.commercial = commercial
    app.state.support = support
    app.include_router(panel_router())

    @app.middleware("http")
    async def private_api_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response
    key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def admin(key: str | None = Depends(key_header)):
        if not key or not secrets.compare_digest(key.encode(), settings.admin_api_key.encode()):
            raise HTTPException(401, "Chave de acesso inválida.")

    @app.get("/v1/ia/status", dependencies=[Depends(admin)], tags=["IA local"])
    def ai_status():
        result = local_ai_status(settings, ai_transport)
        result["inicializacao"] = runtime.state
        result["recursos"] = {"memoria_limite_mb": memory_limit_mb(), "cpu_limite_nucleos": cpu_limit_cores(),
                              "threads_ia": settings.local_ai_threads}
        return result

    @app.exception_handler(CommercialError)
    async def commercial_error(request, error):
        return JSONResponse(status_code=error.status_code, content={"detail": str(error)})

    for router in commercial_routers(commercial, admin):
        app.include_router(router)

    for router in support_routers(support, admin):
        app.include_router(router)

    def session_dependency():
        with sessions() as session:
            yield session

    def get_lead(session, lead_id, lock=False):
        query = select(Lead).where(Lead.id == lead_id)
        if lock:
            query = query.with_for_update()
        lead = session.execute(query).scalar_one_or_none()
        if not lead:
            raise HTTPException(404, "Empresa não encontrada.")
        return lead

    @app.get("/", tags=["Informações"])
    def index():
        return {"projeto": "AtendeAI", "versao": "0.5.2", "documentacao": "/docs", "painel": "/painel",
                "agentes": {"1_pesquisa": "implementado", "2_comercial": "implementado" if settings.whatsapp_ready else "implementado_configuracao_pendente",
                            "3_atendimento": "implementado"},
                "fonte_configurada": source.name, "envio_whatsapp_ativo": settings.whatsapp_ready}

    @app.get("/health", tags=["Informações"])
    def health():
        try:
            with sessions() as session:
                session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            raise HTTPException(503, "Banco indisponível.")
        return {"status": "ok"}

    @app.get("/v1/cidades", dependencies=[Depends(admin)], tags=["Catálogo"])
    def cities():
        return {"uf": "SP", "cobertura": "Catálogo inicial de 20 municípios; não é uma busca exaustiva de todo o estado.",
                "cidades": [{"nome": c.name, "codigo_ibge": c.ibge_code, "area": c.region} for c in CITIES.values()]}

    @app.get("/v1/segmentos", dependencies=[Depends(admin)], tags=["Catálogo"])
    def segments():
        return {"segmentos": [{"id": name, "descricao": detail["label"]} for name, detail in SEGMENTS.items()]}

    @app.post("/v1/buscas", dependencies=[Depends(admin)], tags=["Agente 1"])
    def search(body: SearchRequest):
        try:
            return run_search(sessions, settings, source, resolve_city(body.cidade),
                              body.segmentos, body.limite, body.usar_cache)
        except SourceBusy as exc:
            raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after)})
        except SourceError as exc:
            raise HTTPException(502, str(exc))

    @app.get("/v1/empresas", dependencies=[Depends(admin)], tags=["Empresas"])
    def leads(cidade: str | None = None, segmento: str | None = None,
              demonstracao: bool | None = None, limite: int = Query(100, ge=1, le=1000),
              pagina: int = Query(1, ge=1), session=Depends(session_dependency)):
        query = select(Lead)
        if cidade:
            try:
                canonical = resolve_city(cidade).name
            except ValueError as exc:
                raise HTTPException(422, str(exc))
            query = query.where(Lead.city == canonical)
        if segmento:
            if segmento not in SEGMENTS:
                raise HTTPException(422, "Segmento não suportado.")
            query = query.where(Lead.segment == segmento)
        if demonstracao is not None:
            query = query.where(Lead.is_demo == demonstracao)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.scalars(query.order_by(Lead.priority.desc(), Lead.id).offset((pagina - 1) * limite).limit(limite)).all()
        return {"total": total, "pagina": pagina, "empresas": [serialize_lead(row) for row in rows],
                "atribuicao_dados_osm": "© OpenStreetMap contributors — ODbL 1.0",
                "licenca_dados_osm": "https://opendatacommons.org/licenses/odbl/1-0/"}

    @app.get("/v1/empresas/{lead_id}", dependencies=[Depends(admin)], tags=["Empresas"])
    def lead_detail(lead_id: str, session=Depends(session_dependency)):
        return serialize_lead(get_lead(session, lead_id))

    @app.post("/v1/empresas/{lead_id}/analise", dependencies=[Depends(admin)], tags=["Agente 1"])
    def analysis(lead_id: str, session=Depends(session_dependency)):
        lead = get_lead(session, lead_id)
        try:
            result = analyze(lead, settings, ai_transport)
        except AnalysisError as exc:
            raise HTTPException(502, str(exc))
        # Model output cannot alter consent, identity, geography or published contact data.
        lead.analysis = result
        session.commit()
        return {"empresa_id": lead.id, "analise": result}

    @app.post("/v1/empresas/{lead_id}/revisao", dependencies=[Depends(admin)], tags=["Revisão"])
    def review(lead_id: str, body: ReviewRequest, session=Depends(session_dependency)):
        lead = get_lead(session, lead_id, lock=True)
        lead.review_status, lead.review_note = body.status, body.observacao or None
        session.commit()
        return serialize_lead(lead)

    @app.post("/v1/empresas/{lead_id}/consentimento", dependencies=[Depends(admin)], tags=["Revisão"])
    def consent(lead_id: str, body: ConsentRequest, session=Depends(session_dependency)):
        lead = get_lead(session, lead_id, lock=True)
        if lead.is_demo:
            raise HTTPException(409, "Empresas fictícias não podem entrar na fila comercial.")
        previous = session.scalars(select(ConsentEvent).where(ConsentEvent.lead_id == lead.id)
                                   .order_by(ConsentEvent.occurred_at.desc(), ConsentEvent.registered_at.desc()).limit(1)).first()
        if previous and as_utc(body.ocorrido_em) <= as_utc(previous.occurred_at):
            raise HTTPException(409, "Evento anterior ou repetido: o consentimento mais recente foi preservado.")
        session.add(ConsentEvent(lead_id=lead.id, status=body.status, recipient=body.destinatario_whatsapp,
                                 evidence=body.evidencia, occurred_at=body.ocorrido_em))
        lead.consent_status = body.status
        lead.whatsapp_recipient = body.destinatario_whatsapp if body.status == "concedido" else None
        session.commit()
        return serialize_lead(lead)

    @app.get("/v1/comercial/fila", dependencies=[Depends(admin)], tags=["Agente 2"])
    def commercial_queue(limite: int = Query(100, ge=1, le=1000), session=Depends(session_dependency)):
        query = select(Lead).where(Lead.is_demo.is_(False), Lead.review_status == "aprovada",
                                   Lead.consent_status == "concedido", Lead.whatsapp_recipient.is_not(None))
        rows = session.scalars(query.order_by(Lead.priority.desc(), Lead.id).limit(limite)).all()
        return {"quantidade": len(rows), "empresas": [serialize_lead(row) for row in rows],
                "envio_ativo": settings.whatsapp_ready, "etapa": "Empresas autorizadas para preparar e revisar a abordagem comercial."}

    return app
