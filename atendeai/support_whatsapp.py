"""Webhooks e respostas de suporte isolados por empresa e número remetente."""
from datetime import timedelta
import re

from sqlalchemy import select, update

from .commercial_inbox import array_field, is_opt_out, normalize_text, recipient, timestamp
from .models import SupportConversation, SupportHandoff, SupportMessage, WhatsAppStatusEvent, as_utc, utcnow
from .service import db_insert
from .whatsapp import WhatsAppClient, WhatsAppRejected, WhatsAppUncertain


def apply_delivery(session, message, phone):
    if not message.provider_message_id:
        return
    ranking = {None: 0, "sent": 1, "delivered": 2, "read": 3}
    for event in session.scalars(select(WhatsAppStatusEvent).where(
            WhatsAppStatusEvent.provider_message_id == message.provider_message_id, WhatsAppStatusEvent.recipient == phone)
            .order_by(WhatsAppStatusEvent.occurred_at)):
        if event.status == "failed" and message.delivery_status not in {"delivered", "read"}:
            message.delivery_status, message.status = "failed", "falhou"
            message.error = "Meta informou falha na entrega, código " + (event.error_code or "não informado") + "."
        elif ranking.get(event.status, 0) > ranking.get(message.delivery_status, 0):
            message.delivery_status = event.status
            if message.status == "falhou":
                message.status, message.error = "aceita", None


def receive(service, tenant_id, payload):
    account = service.account_settings(tenant_id)
    if not account.whatsapp_ready or not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return
    with service.sessions() as session:
        service.tenant(session, tenant_id, active=True)
    for entry in array_field(payload, "entry"):
        for change in array_field(entry, "changes"):
            value = change.get("value", {}) if isinstance(change, dict) else {}
            metadata = value.get("metadata", {}) if isinstance(value, dict) else {}
            if not isinstance(metadata, dict) or str(metadata.get("phone_number_id", "")) != account.whatsapp_phone_number_id:
                continue
            for raw in array_field(value, "messages"):
                if not isinstance(raw, dict):
                    continue
                phone, occurred, remote_id = recipient(raw.get("from")), timestamp(raw.get("timestamp")), raw.get("id")
                if not phone or not occurred or not isinstance(remote_id, str) or not 1 <= len(remote_id) <= 250:
                    continue
                text_object = raw.get("text", {})
                kind = "text" if raw.get("type") == "text" else "midia"
                text = text_object.get("body", "") if kind == "text" and isinstance(text_object, dict) else "[Mensagem de mídia recebida]"
                if not isinstance(text, str) or not text.strip():
                    continue
                with service.sessions() as session:
                    tenant = service.tenant(session, tenant_id, active=True, lock=True)
                    if session.scalar(select(SupportMessage.id).where(SupportMessage.provider_message_id == remote_id)):
                        continue
                    conversation = session.scalar(select(SupportConversation).where(SupportConversation.tenant_id == tenant_id,
                        SupportConversation.channel == "whatsapp", SupportConversation.recipient == phone).with_for_update())
                    if not conversation:
                        if not service.reserve(session, tenant, "conversations_opened", tenant.daily_conversation_limit):
                            from .commercial import CommercialError
                            raise CommercialError("Limite de novas conversas atingido.", 429)
                        conversation = SupportConversation(tenant_id=tenant_id, channel="whatsapp", recipient=phone)
                        session.add(conversation)
                        session.flush()
                    message = SupportMessage(tenant_id=tenant_id, conversation_id=conversation.id, direction="entrada",
                        author="cliente", kind=kind, text=text[:8000], provider_message_id=remote_id,
                        occurred_at=occurred, status="recebida")
                    session.add(message)
                    session.flush()
                    if not conversation.last_inbound_at or occurred >= as_utc(conversation.last_inbound_at):
                        conversation.last_inbound_at, conversation.last_inbound_id = occurred, message.id
                    restart = normalize_text(text) in {"retomar", "reiniciar atendimento", "quero atendimento novamente"}
                    if restart and conversation.opted_out_at and occurred > as_utc(conversation.opted_out_at):
                        conversation.state, conversation.pause_reason, conversation.opted_out_at = "bot", None, None
                        conversation.resumed_at, conversation.auto_replies = occurred, 0
                        service.add_reply(session, conversation, tenant.welcome_text, "assistente", message, "boas_vindas")
                        message.status = "processada"
                    elif is_opt_out(text) and (not conversation.resumed_at or occurred > as_utc(conversation.resumed_at)):
                        conversation.state, conversation.pause_reason = "interrompida", "pedido_interrupcao"
                        conversation.opted_out_at = occurred
                        service.cancel_pending(session, conversation.id)
                        session.execute(update(SupportMessage).where(SupportMessage.conversation_id == conversation.id,
                            SupportMessage.status == "na_fila").values(status="cancelada"))
                        session.execute(update(SupportHandoff).where(SupportHandoff.conversation_id == conversation.id,
                            SupportHandoff.status == "aberto").values(status="interrompido", closed_at=utcnow()))
                        message.status = "processada"
                    elif is_opt_out(text):
                        message.status = "processada"
                    session.commit()
            for raw in array_field(value, "statuses"):
                if not isinstance(raw, dict) or raw.get("status") not in {"sent", "delivered", "read", "failed"}:
                    continue
                phone, occurred, remote_id = recipient(raw.get("recipient_id")), timestamp(raw.get("timestamp")), raw.get("id")
                if not phone or not occurred or not isinstance(remote_id, str) or not 1 <= len(remote_id) <= 250:
                    continue
                errors = array_field(raw, "errors")
                code = str(errors[0].get("code", "")) if errors and isinstance(errors[0], dict) else ""
                code = code if re.fullmatch(r"\d{1,20}", code) else None
                with service.sessions() as session:
                    session.execute(db_insert(session, WhatsAppStatusEvent).values(provider_message_id=remote_id,
                        recipient=phone, status=raw["status"], occurred_at=occurred, error_code=code)
                        .on_conflict_do_nothing(index_elements=["provider_message_id", "status", "occurred_at"]))
                    message = session.scalar(select(SupportMessage).where(SupportMessage.tenant_id == tenant_id,
                        SupportMessage.direction == "saida", SupportMessage.provider_message_id == remote_id).with_for_update())
                    if message:
                        apply_delivery(session, message, phone)
                    session.commit()


def process_outbound(service):
    now = utcnow()
    with service.sessions() as session:
        session.execute(update(SupportMessage).where(SupportMessage.status == "processando",
            SupportMessage.processing_at < now - timedelta(minutes=3)).values(status="envio_incerto",
                error="Processamento interrompido; envio não repetido automaticamente."))
        identifier = session.scalar(select(SupportMessage.id).where(SupportMessage.direction == "saida",
            SupportMessage.status == "na_fila").order_by(SupportMessage.created_at, SupportMessage.id).limit(1))
        if not identifier:
            session.commit()
            return 0
        claimed = session.execute(update(SupportMessage).where(SupportMessage.id == identifier,
            SupportMessage.status == "na_fila").values(status="processando", processing_at=now))
        session.commit()
        if claimed.rowcount != 1:
            return 0
    with service.sessions() as session:
        message = session.get(SupportMessage, identifier)
        tenant = service.tenant(session, message.tenant_id, lock=True)
        conversation = service.conversation(session, tenant.id, message.conversation_id, lock=True)
        account = service.account_settings(tenant.id)
        reason = None
        if not tenant.active or not account.whatsapp_ready:
            reason = "Empresa ou conta WhatsApp desativada/não configurada."
        elif conversation.channel != "whatsapp" or conversation.opted_out_at or conversation.state == "interrompida":
            reason = "Canal inválido ou conversa interrompida pelo cliente."
        elif message.sender_id != account.whatsapp_phone_number_id:
            reason = "O número remetente foi alterado."
        elif not conversation.last_inbound_at or as_utc(conversation.last_inbound_at) + timedelta(hours=24) <= now:
            reason = "A janela de resposta de 24 horas encerrou."
        elif message.author == "assistente" and (conversation.state != "bot" or message.reply_to_id != conversation.last_inbound_id):
            reason = "Atendimento humano ou nova mensagem tornou a resposta anterior inválida."
        if reason:
            message.status, message.error = "bloqueada", reason
            session.commit()
            return 1
        message.attempts += 1
        session.commit()
    with service.sessions() as session:
        message = session.get(SupportMessage, identifier)
        tenant = service.tenant(session, message.tenant_id, lock=True)
        conversation = service.conversation(session, tenant.id, message.conversation_id, lock=True)
        if not tenant.active or conversation.opted_out_at or conversation.state == "interrompida" or (
                message.author == "assistente" and (conversation.state != "bot" or message.reply_to_id != conversation.last_inbound_id)) or (
                not conversation.last_inbound_at or as_utc(conversation.last_inbound_at) + timedelta(hours=24) <= utcnow()):
            message.status, message.error = "bloqueada", "O estado da conversa não permite mais esta resposta."
        else:
            try:
                message.provider_message_id = WhatsAppClient(account, service.whatsapp_transport).send({
                    "messaging_product": "whatsapp", "to": conversation.recipient.lstrip("+"), "type": "text",
                    "text": {"preview_url": False, "body": message.text}})
                message.status = "aceita"
                apply_delivery(session, message, conversation.recipient)
            except WhatsAppRejected as error:
                message.status, message.error = "falhou", str(error)
            except WhatsAppUncertain as error:
                message.status, message.error = "envio_incerto", str(error)
        session.commit()
    return 1
