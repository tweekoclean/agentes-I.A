import asyncio
import hashlib
import hmac
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from .commercial import CommercialError
from .models import SupportConversation, SupportHandoff, SupportKnowledge, SupportMessage, SupportTenant, as_utc, utcnow
from .support import DEMO_SITE_KEY, DEMO_TENANT_ID, digest, support_conversation_data, support_message_data


class SupportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


def origins(values):
    result = []
    for value in values:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password or
                parsed.path not in {"", "/"} or parsed.query or parsed.fragment or
                (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"})):
            raise ValueError("Use origens HTTPS completas, sem caminho; HTTP somente para localhost.")
        normalized = f"{parsed.scheme}://{parsed.netloc.lower()}"
        if normalized not in result:
            result.append(normalized)
    return result


class TenantCreate(SupportBody):
    nome: str = Field(min_length=2, max_length=200)
    origens_permitidas: list[str] = Field(default_factory=list, max_length=20)
    boas_vindas: str = Field(default="Olá! Sou o assistente virtual de atendimento. Como posso ajudar?", min_length=1, max_length=2000)
    ia_habilitada: bool = False
    limite_conversas_dia: int = Field(100, ge=1, le=10000)
    limite_ia_dia: int = Field(100, ge=1, le=10000)
    _origins = field_validator("origens_permitidas")(origins)


class TenantPatch(SupportBody):
    ativa: bool | None = None
    ia_habilitada: bool | None = None
    origens_permitidas: list[str] | None = Field(None, max_length=20)
    boas_vindas: str | None = Field(None, min_length=1, max_length=2000)
    limite_conversas_dia: int | None = Field(None, ge=1, le=10000)
    limite_ia_dia: int | None = Field(None, ge=1, le=10000)

    @field_validator("origens_permitidas")
    @classmethod
    def origin_values(cls, value):
        return origins(value) if value is not None else value


class KnowledgeBody(SupportBody):
    titulo: str = Field(min_length=2, max_length=200)
    conteudo: str = Field(min_length=1, max_length=2000)
    ativa: bool = True


class SiteMessageBody(SupportBody):
    texto: str = Field(min_length=1, max_length=4000)
    id_cliente: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")

    @field_validator("texto")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Informe uma mensagem.")
        return value.strip()


class HumanMessageBody(SupportBody):
    texto: str = Field(min_length=1, max_length=2000)
    _text = field_validator("texto")(SiteMessageBody.nonblank.__func__)


class SupportPause(SupportBody):
    pausado: bool


def knowledge_data(row):
    return {"id": row.id, "empresa_id": row.tenant_id, "titulo": row.title, "conteudo": row.content, "ativa": row.active}


def bearer(header):
    return header[7:] if header and header.startswith("Bearer ") else ""


def support_routers(service, admin):
    protected = APIRouter(prefix="/v1/atendimento", dependencies=[Depends(admin)], tags=["Agente 3 — administração"])
    public = APIRouter(tags=["Agente 3 — site e webhook"])

    @protected.post("/empresas")
    def create(body: TenantCreate):
        return service.create_tenant(body)

    @protected.get("/empresas")
    def tenants(limite: int = Query(100, ge=1, le=1000), pagina: int = Query(1, ge=1)):
        with service.sessions() as session:
            rows = session.scalars(select(SupportTenant).order_by(SupportTenant.created_at)
                .offset((pagina - 1) * limite).limit(limite)).all()
            return {"empresas": [service.tenant_data(row) for row in rows], "pagina": pagina}

    @protected.patch("/empresas/{tenant_id}")
    def tenant_patch(tenant_id: str, body: TenantPatch):
        fields = {"ativa": "active", "ia_habilitada": "ai_enabled", "origens_permitidas": "allowed_origins",
                  "boas_vindas": "welcome_text", "limite_conversas_dia": "daily_conversation_limit", "limite_ia_dia": "daily_ai_limit"}
        with service.sessions() as session:
            row = service.tenant(session, tenant_id, lock=True)
            for name, value in body.model_dump(exclude_none=True).items():
                setattr(row, fields[name], value)
            session.commit()
            return service.tenant_data(row)

    @protected.post("/empresas/{tenant_id}/chave-site")
    def rotate_key(tenant_id: str):
        with service.sessions() as session:
            row = service.tenant(session, tenant_id, lock=True)
            key = secrets.token_urlsafe(32)
            row.site_key_hash = digest(key)
            session.commit()
            return {"empresa_id": tenant_id, "chave_site": key}

    @protected.post("/empresas/{tenant_id}/base")
    def create_knowledge(tenant_id: str, body: KnowledgeBody):
        with service.sessions() as session:
            service.tenant(session, tenant_id)
            row = SupportKnowledge(tenant_id=tenant_id, title=body.titulo, content=body.conteudo, active=body.ativa)
            session.add(row)
            session.commit()
            return knowledge_data(row)

    @protected.get("/empresas/{tenant_id}/base")
    def knowledge(tenant_id: str, limite: int = Query(100, ge=1, le=1000), pagina: int = Query(1, ge=1)):
        with service.sessions() as session:
            service.tenant(session, tenant_id)
            rows = session.scalars(select(SupportKnowledge).where(SupportKnowledge.tenant_id == tenant_id)
                .order_by(SupportKnowledge.created_at).offset((pagina - 1) * limite).limit(limite)).all()
            return {"base": [knowledge_data(row) for row in rows], "pagina": pagina}

    @protected.put("/empresas/{tenant_id}/base/{knowledge_id}")
    def update_knowledge(tenant_id: str, knowledge_id: str, body: KnowledgeBody):
        with service.sessions() as session:
            service.tenant(session, tenant_id)
            row = session.scalar(select(SupportKnowledge).where(SupportKnowledge.id == knowledge_id,
                SupportKnowledge.tenant_id == tenant_id).with_for_update())
            if not row:
                raise CommercialError("Item da base não encontrado nesta empresa.", 404)
            row.title, row.content, row.active, row.updated_at = body.titulo, body.conteudo, body.ativa, utcnow()
            session.commit()
            return knowledge_data(row)

    @protected.get("/empresas/{tenant_id}/conversas")
    def conversations(tenant_id: str, limite: int = Query(100, ge=1, le=1000), pagina: int = Query(1, ge=1)):
        with service.sessions() as session:
            service.tenant(session, tenant_id)
            rows = session.scalars(select(SupportConversation).where(SupportConversation.tenant_id == tenant_id)
                .order_by(SupportConversation.created_at.desc()).offset((pagina - 1) * limite).limit(limite)).all()
            return {"conversas": [support_conversation_data(row) for row in rows], "pagina": pagina}

    @protected.get("/empresas/{tenant_id}/conversas/{conversation_id}")
    def history(tenant_id: str, conversation_id: str, limite: int = Query(100, ge=1, le=1000), pagina: int = Query(1, ge=1)):
        with service.sessions() as session:
            conversation = service.conversation(session, tenant_id, conversation_id)
            rows = session.scalars(select(SupportMessage).where(SupportMessage.conversation_id == conversation.id)
                .order_by(SupportMessage.created_at.desc(), SupportMessage.id).offset((pagina - 1) * limite).limit(limite)).all()
            return {"conversa": support_conversation_data(conversation), "pagina": pagina,
                    "mensagens": [support_message_data(row, private=True) for row in reversed(rows)]}

    @protected.post("/empresas/{tenant_id}/conversas/{conversation_id}/responder")
    def human(tenant_id: str, conversation_id: str, body: HumanMessageBody):
        return service.human_reply(tenant_id, conversation_id, body.texto)

    @protected.post("/empresas/{tenant_id}/conversas/{conversation_id}/pausa")
    def pause(tenant_id: str, conversation_id: str, body: SupportPause):
        return service.pause(tenant_id, conversation_id, body.pausado)

    @protected.get("/empresas/{tenant_id}/chamados")
    def tickets(tenant_id: str, status: str = "aberto", limite: int = Query(100, ge=1, le=1000), pagina: int = Query(1, ge=1)):
        with service.sessions() as session:
            service.tenant(session, tenant_id)
            rows = session.scalars(select(SupportHandoff).where(SupportHandoff.tenant_id == tenant_id,
                SupportHandoff.status == status).order_by(SupportHandoff.created_at).offset((pagina - 1) * limite).limit(limite)).all()
            return {"chamados": [{"id": row.id, "conversa_id": row.conversation_id, "motivo": row.reason,
                "resumo": row.summary, "status": row.status, "criado_em": as_utc(row.created_at).isoformat()} for row in rows], "pagina": pagina}

    @protected.post("/processar")
    def process():
        return service.process_cycle()

    @public.get("/widget/atendeai.js")
    def widget():
        return FileResponse(Path(__file__).parent / "static" / "widget.js", media_type="application/javascript",
                            headers={"Cache-Control": "public, max-age=300"})

    @public.get("/demonstracao", include_in_schema=False)
    def demonstration():
        if not service.settings.support_demo_enabled:
            raise HTTPException(404, "Demonstração desativada.")
        with service.sessions() as session:
            service.tenant(session, DEMO_TENANT_ID, active=True)
        return RedirectResponse(f"/teste-atendimento?empresa={DEMO_TENANT_ID}&chave={DEMO_SITE_KEY}")

    @public.get("/teste-atendimento", include_in_schema=False)
    def test_chat():
        return FileResponse(Path(__file__).parent / "static" / "test-chat.html", media_type="text/html",
                            headers={"Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})

    @public.post("/v1/atendimento/site/{tenant_id}/conversas")
    def open_conversation(tenant_id: str, response: Response, x_site_key: str | None = Header(None), origin: str | None = Header(None)):
        response.headers["Cache-Control"] = "no-store"
        return service.site_conversation(tenant_id, x_site_key, origin)

    @public.post("/v1/atendimento/site/{tenant_id}/conversas/{conversation_id}/mensagens")
    def send_site(tenant_id: str, conversation_id: str, body: SiteMessageBody, response: Response,
                  authorization: str | None = Header(None), origin: str | None = Header(None)):
        response.headers["Cache-Control"] = "no-store"
        return service.site_message(tenant_id, conversation_id, bearer(authorization), origin, body.texto, body.id_cliente)

    @public.get("/v1/atendimento/site/{tenant_id}/conversas/{conversation_id}/mensagens")
    def site_history(tenant_id: str, conversation_id: str, response: Response,
                     authorization: str | None = Header(None), origin: str | None = Header(None)):
        with service.sessions() as session:
            conversation = service.visitor_access(session, tenant_id, conversation_id, bearer(authorization), origin)
            rows = session.scalars(select(SupportMessage).where(SupportMessage.conversation_id == conversation.id)
                .order_by(SupportMessage.created_at, SupportMessage.id).limit(200)).all()
            response.headers["Cache-Control"] = "no-store"
            return {"conversa": support_conversation_data(conversation), "mensagens": [support_message_data(row) for row in rows]}

    @public.get("/webhooks/atendimento/whatsapp/{tenant_id}")
    def verify(tenant_id: str, mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"),
               challenge: str = Query(alias="hub.challenge", max_length=300)):
        account = service.account_settings(tenant_id)
        with service.sessions() as session:
            service.tenant(session, tenant_id, active=True)
        if not account.whatsapp_ready:
            raise HTTPException(503, "Configure e habilite o WhatsApp desta empresa.")
        if mode != "subscribe" or not secrets.compare_digest(token.encode(), account.whatsapp_verify_token.encode()):
            raise HTTPException(403, "Verificação do webhook inválida.")
        return PlainTextResponse(challenge)

    @public.post("/webhooks/atendimento/whatsapp/{tenant_id}")
    async def webhook(tenant_id: str, request: Request):
        account = service.account_settings(tenant_id)
        if not account.whatsapp_ready:
            raise HTTPException(503, "Configure e habilite o WhatsApp desta empresa.")
        chunks, total = [], 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > 1024 * 1024:
                raise HTTPException(413, "Evento acima do tamanho permitido.")
            chunks.append(chunk)
        body = b"".join(chunks)
        expected = "sha256=" + hmac.new(account.whatsapp_app_secret.encode(), body, hashlib.sha256).hexdigest()
        if not secrets.compare_digest(expected.encode(), request.headers.get("X-Hub-Signature-256", "").encode()):
            raise HTTPException(401, "Assinatura do webhook inválida.")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Evento JSON inválido.") from None
        from .support_whatsapp import receive
        await asyncio.to_thread(receive, service, tenant_id, payload)
        return {"status": "ok"}

    return protected, public
