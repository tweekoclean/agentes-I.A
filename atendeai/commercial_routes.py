import asyncio
import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .commercial import conversation_data, message_data
from .models import CommercialConversation, CommercialHandoff, CommercialMessage, as_utc


class CommercialBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftRequest(CommercialBody):
    empresa_id: str = Field(min_length=1, max_length=36)


class ApprovalRequest(CommercialBody):
    aprovar: bool


class PauseRequest(CommercialBody):
    pausado: bool


def commercial_routers(service, admin):
    protected = APIRouter(prefix="/v1/comercial", dependencies=[Depends(admin)], tags=["Agente 2"])
    public = APIRouter(tags=["Webhook WhatsApp"])

    @protected.get("/status")
    def status():
        return service.status()

    @protected.post("/rascunhos")
    def draft(body: DraftRequest):
        return service.draft(body.empresa_id)

    @protected.get("/mensagens")
    def messages(empresa_id: str | None = None, status: str | None = None,
                 limite: int = Query(100, ge=1, le=1000), pagina: int = Query(1, ge=1)):
        with service.sessions() as session:
            query = select(CommercialMessage)
            if empresa_id:
                query = query.where(CommercialMessage.lead_id == empresa_id)
            if status:
                query = query.where(CommercialMessage.status == status)
            rows = session.scalars(query.order_by(CommercialMessage.created_at.desc(), CommercialMessage.id)
                                   .offset((pagina - 1) * limite).limit(limite)).all()
            return {"pagina": pagina, "mensagens": [message_data(row) for row in rows]}

    @protected.post("/mensagens/{message_id}/revisao")
    def review(message_id: str, body: ApprovalRequest):
        return service.review(message_id, body.aprovar)

    @protected.post("/mensagens/{message_id}/enfileirar")
    def enqueue(message_id: str):
        return service.enqueue(message_id)

    @protected.post("/mensagens/{message_id}/cancelar")
    def cancel(message_id: str):
        return service.cancel(message_id)

    @protected.post("/processar")
    def process():
        """Processa uma entrada e um envio. Também existe processamento automático no servidor."""
        return service.process_cycle()

    @protected.get("/conversas")
    def conversations(limite: int = Query(100, ge=1, le=1000), pagina: int = Query(1, ge=1)):
        with service.sessions() as session:
            rows = session.scalars(select(CommercialConversation).order_by(CommercialConversation.created_at.desc())
                .offset((pagina - 1) * limite).limit(limite)).all()
            return {"pagina": pagina, "conversas": [conversation_data(row) for row in rows]}

    @protected.get("/conversas/{conversation_id}")
    def conversation(conversation_id: str, limite: int = Query(100, ge=1, le=1000), pagina: int = Query(1, ge=1)):
        with service.sessions() as session:
            row = service._get(session, CommercialConversation, conversation_id, "Conversa")
            messages = session.scalars(select(CommercialMessage).where(CommercialMessage.conversation_id == row.id)
                .order_by(CommercialMessage.created_at.desc(), CommercialMessage.id)
                .offset((pagina - 1) * limite).limit(limite)).all()
            return {"conversa": conversation_data(row), "pagina": pagina,
                    "mensagens": [message_data(message) for message in reversed(messages)]}

    @protected.post("/conversas/{conversation_id}/pausa")
    def pause(conversation_id: str, body: PauseRequest):
        return service.pause(conversation_id, body.pausado)

    @protected.get("/encaminhamentos")
    def handoffs(status: str = "aberto", limite: int = Query(100, ge=1, le=1000), pagina: int = Query(1, ge=1)):
        with service.sessions() as session:
            rows = session.scalars(select(CommercialHandoff).where(CommercialHandoff.status == status)
                .order_by(CommercialHandoff.created_at).offset((pagina - 1) * limite).limit(limite)).all()
            return {"pagina": pagina, "encaminhamentos": [
                {"id": row.id, "conversa_id": row.conversation_id, "motivo": row.reason,
                 "resumo": row.summary, "status": row.status,
                 "criado_em": as_utc(row.created_at).isoformat()} for row in rows]}

    @public.get("/webhooks/whatsapp")
    def verify(mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"),
               challenge: str = Query(alias="hub.challenge", max_length=300)):
        if not service.settings.whatsapp_verify_token:
            raise HTTPException(503, "Configure WHATSAPP_VERIFY_TOKEN.")
        if mode != "subscribe" or not secrets.compare_digest(token.encode(), service.settings.whatsapp_verify_token.encode()):
            raise HTTPException(403, "Verificação do webhook inválida.")
        return PlainTextResponse(challenge)

    @public.post("/webhooks/whatsapp")
    async def webhook(request: Request):
        if not service.settings.whatsapp_app_secret:
            raise HTTPException(503, "Configure WHATSAPP_APP_SECRET.")
        chunks, total = [], 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > 1024 * 1024:
                raise HTTPException(413, "Evento acima do tamanho permitido.")
            chunks.append(chunk)
        body = b"".join(chunks)
        expected = "sha256=" + hmac.new(service.settings.whatsapp_app_secret.encode(), body, hashlib.sha256).hexdigest()
        supplied = request.headers.get("X-Hub-Signature-256", "")
        if not secrets.compare_digest(expected.encode(), supplied.encode()):
            raise HTTPException(401, "Assinatura do webhook inválida.")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, "Evento JSON inválido.") from None
        await asyncio.to_thread(service.receive, payload)
        return {"status": "ok"}

    return protected, public
