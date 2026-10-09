"""Aplicações públicas e funil privado da Nelvo; nenhuma mensagem é enviada aqui."""
from datetime import timedelta
import hashlib
import hmac
import secrets
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from .catalog import CITIES, SEGMENTS, resolve_city
from .models import (ApplicationRate, Lead, SalesApplication, SupportHandoff,
                     SupportTenant, as_utc, utcnow)
from .service import db_insert
from .sources import normalize_phone
from .support import DEMO_TENANT_ID, digest
from .support_routes import TenantCreate

STAGES = {"nova": "Novas", "qualificacao": "Qualificação", "demonstracao": "Demonstração",
          "proposta": "Proposta", "ganha": "Contratadas", "perdida": "Arquivadas"}
Stage = Literal["nova", "qualificacao", "demonstracao", "proposta", "ganha", "perdida"]


class ApplicationBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id_envio: UUID
    nome_empresa: str = Field(min_length=2, max_length=200)
    cidade: str = Field(min_length=2, max_length=100)
    segmento: str = Field(min_length=2, max_length=50)
    nome_contato: str = Field(min_length=2, max_length=150)
    whatsapp: str = Field(min_length=10, max_length=30)
    canais: list[Literal["whatsapp", "site"]] = Field(min_length=1, max_length=2)
    volume: Literal["ate_30", "31_100", "101_300", "mais_300", "nao_sei"]
    objetivo: str = Field(min_length=10, max_length=2000)
    autoriza_contato: Literal[True]
    site_extra: str = Field(default="", max_length=200)

    @field_validator("cidade")
    @classmethod
    def city(cls, value):
        return resolve_city(value).name

    @field_validator("segmento")
    @classmethod
    def segment(cls, value):
        if value not in SEGMENTS:
            raise ValueError("Selecione um segmento disponível.")
        return value

    @field_validator("whatsapp")
    @classmethod
    def phone(cls, value):
        phone = normalize_phone(value)
        if not phone:
            raise ValueError("Informe um telefone brasileiro com DDD.")
        return phone


class FunnelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    etapa: Stage
    notas: str = Field(default="", max_length=4000)


class LeadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    empresa_id: UUID


def application_data(row):
    return {"id": row.id, "empresa_id": row.lead_id, "cliente_id": row.tenant_id,
            "nome_empresa": row.name, "cidade": row.city, "segmento": row.segment,
            "nome_contato": row.contact_name, "whatsapp": row.phone, "canais": row.channels,
            "volume": row.volume, "objetivo": row.goals, "autoriza_contato": row.contact_permission,
            "origem": row.source, "etapa": row.stage, "notas": row.notes,
            "criada_em": as_utc(row.created_at).isoformat(), "atualizada_em": as_utc(row.updated_at).isoformat()}


def funnel_routers(sessions, settings, support, admin):
    public = APIRouter(prefix="/publico/aplicacoes", tags=["Aplicação comercial"])
    private = APIRouter(prefix="/v1/funil", dependencies=[Depends(admin)], tags=["Funil da Nelvo"])

    def get_application(session, identifier):
        row = session.scalar(select(SalesApplication).where(SalesApplication.id == identifier).with_for_update())
        if not row:
            raise HTTPException(404, "Aplicação não encontrada.")
        return row

    def receipt(row):
        return {"protocolo": row.id, "mensagem": "Aplicação recebida. A Nelvo vai analisar sua necessidade de atendimento."}

    @public.get("/catalogo")
    def catalog():
        return {"cidades": [city.name for city in CITIES.values()],
                "segmentos": [{"id": key, "nome": value["label"]} for key, value in SEGMENTS.items()]}

    @public.post("", status_code=201)
    async def submit(request: Request):
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.url.netloc:
            raise HTTPException(403, "Envie a aplicação pelo formulário da Nelvo.")
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            raise HTTPException(415, "Use application/json.")
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
                raise HTTPException(413, "Aplicação muito grande.")
        try:
            body = ApplicationBody.model_validate_json(raw)
        except ValidationError:
            raise HTTPException(422, "Confira os campos, o telefone com DDD e a autorização de contato.") from None
        if body.site_extra:
            raise HTTPException(422, "Não foi possível enviar a aplicação.")
        now = utcnow()
        # IP da conexão, sem confiar em cabeçalhos enviados pelo visitante. Só o hash é persistido.
        address = request.client.host if request.client else "unknown"
        address_hash = hmac.new(settings.admin_api_key.encode(), (address + ":" + body.whatsapp).encode(), hashlib.sha256).hexdigest()
        limits = [("ip:" + address_hash + now.strftime(":%Y%m%d%H"), 5, now + timedelta(hours=2)),
                  ("global:" + now.strftime("%Y%m%d"), 100, now + timedelta(days=2))]
        try:
            with sessions() as session:
                existing = session.scalar(select(SalesApplication).where(SalesApplication.submission_id == str(body.id_envio)))
                if existing:
                    return receipt(existing)
                session.execute(delete(ApplicationRate).where(ApplicationRate.expires_at < now))
                for key, maximum, expiry in limits:
                    session.execute(db_insert(session, ApplicationRate).values(key=key, attempts=0, expires_at=expiry)
                                    .on_conflict_do_nothing(index_elements=["key"]))
                    result = session.execute(update(ApplicationRate).where(ApplicationRate.key == key,
                                             ApplicationRate.attempts < maximum).values(attempts=ApplicationRate.attempts + 1))
                    if result.rowcount != 1:
                        raise HTTPException(429, "Limite de aplicações atingido. Tente novamente mais tarde.")
                row = SalesApplication(submission_id=str(body.id_envio), name=body.nome_empresa, city=body.cidade,
                    segment=body.segmento, contact_name=body.nome_contato, phone=body.whatsapp,
                    channels=sorted(set(body.canais)), volume=body.volume, goals=body.objetivo,
                    contact_permission=True, source="aplicacao")
                session.add(row)
                session.commit()
                return receipt(row)
        except IntegrityError:
            with sessions() as session:
                existing = session.scalar(select(SalesApplication).where(SalesApplication.submission_id == str(body.id_envio)))
                if existing:
                    return receipt(existing)
            raise HTTPException(409, "Não foi possível concluir. Atualize antes de tentar novamente.") from None

    @private.get("/resumo")
    def summary():
        with sessions() as session:
            stages = dict(session.execute(select(SalesApplication.stage, func.count()).group_by(SalesApplication.stage)).all())
            leads = session.scalar(select(func.count()).select_from(Lead).where(Lead.is_demo.is_(False)))
            customers = session.scalar(select(func.count()).select_from(SupportTenant).where(SupportTenant.id != DEMO_TENANT_ID))
            tickets = session.scalar(select(func.count()).select_from(SupportHandoff).where(SupportHandoff.status == "aberto"))
        return {"empresas_encontradas": leads, "clientes": customers, "chamados_abertos": tickets,
                "etapas": [{"id": stage, "nome": label, "quantidade": stages.get(stage, 0)} for stage, label in STAGES.items()]}

    @private.get("")
    def listing(etapa: Stage | None = None, busca: str = Query("", max_length=100),
                limite: int = Query(50, ge=1, le=200), pagina: int = Query(1, ge=1)):
        query = select(SalesApplication)
        if etapa:
            query = query.where(SalesApplication.stage == etapa)
        if busca.strip():
            query = query.where(SalesApplication.name.ilike("%" + busca.strip().replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
        with sessions() as session:
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            rows = session.scalars(query.order_by(SalesApplication.updated_at.desc(), SalesApplication.id)
                                   .offset((pagina - 1) * limite).limit(limite)).all()
            return {"total": total, "aplicacoes": [application_data(row) for row in rows]}

    @private.post("/empresas")
    def add_lead(body: LeadBody):
        with sessions() as session:
            lead = session.scalar(select(Lead).where(Lead.id == str(body.empresa_id)).with_for_update())
            if not lead:
                raise HTTPException(404, "Empresa não encontrada.")
            if lead.is_demo:
                raise HTTPException(409, "Dados de demonstração não entram no funil real.")
            existing = session.scalar(select(SalesApplication).where(SalesApplication.lead_id == lead.id))
            if existing:
                return application_data(existing)
            row = SalesApplication(lead_id=lead.id, name=lead.name[:200], city=lead.city, segment=lead.segment,
                                   phone=lead.phone_normalized, source="pesquisa", channels=["whatsapp"])
            session.add(row)
            session.commit()
            return application_data(row)

    @private.patch("/{identifier}")
    def change(identifier: str, body: FunnelPatch):
        with sessions() as session:
            row = get_application(session, identifier)
            if row.tenant_id and body.etapa != "ganha":
                raise HTTPException(409, "Esta aplicação já possui um cliente cadastrado. Gerencie o serviço em Clientes.")
            row.stage, row.notes, row.updated_at = body.etapa, body.notas.strip(), utcnow()
            session.commit()
            return application_data(row)

    @private.post("/{identifier}/empresa")
    def commercial_lead(identifier: str):
        with sessions() as session:
            row = get_application(session, identifier)
            if row.lead_id:
                return {"empresa_id": row.lead_id}
            city = resolve_city(row.city)
            lead = Lead(name=row.name, city=row.city, city_ibge=city.ibge_code, segment=row.segment,
                        phone_normalized=row.phone, source="aplicacao", source_ref=row.id,
                        source_url="/aplicar", source_license="Dados fornecidos pela empresa no formulário",
                        is_demo=False, review_status="pendente", consent_status="desconhecido")
            session.add(lead)
            session.flush()
            row.lead_id, row.updated_at = lead.id, utcnow()
            session.commit()
            return {"empresa_id": lead.id}

    @private.post("/{identifier}/cliente")
    def convert(identifier: str, body: TenantCreate):
        # Cadastro e vínculo na mesma transação: repetir a ação nunca cria dois clientes.
        with sessions() as session:
            row = get_application(session, identifier)
            if row.tenant_id:
                return {"empresa": support.tenant_data(session.get(SupportTenant, row.tenant_id)), "ja_cadastrada": True}
            if row.stage != "ganha":
                raise HTTPException(409, "Marque a aplicação como contratada antes de criar o espaço do cliente.")
            key = secrets.token_urlsafe(32)
            tenant = SupportTenant(name=body.nome, allowed_origins=body.origens_permitidas, welcome_text=body.boas_vindas,
                site_key_hash=digest(key), ai_enabled=body.ia_habilitada, daily_conversation_limit=body.limite_conversas_dia,
                daily_ai_limit=body.limite_ia_dia)
            session.add(tenant)
            session.flush()
            row.tenant_id, row.updated_at = tenant.id, utcnow()
            session.commit()
            return {"empresa": {**support.tenant_data(tenant), "chave_site": key}, "ja_cadastrada": False}

    return public, private
