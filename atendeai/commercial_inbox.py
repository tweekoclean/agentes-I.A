from datetime import datetime, timedelta, timezone
import re
import unicodedata

from sqlalchemy import select, update

from .commercial_brain import decide_reply
from .models import (CommercialConversation, CommercialMessage, ConsentEvent,
                     Lead, WhatsAppStatusEvent, as_utc, utcnow)
from .service import db_insert


def normalize_text(text):
    return " ".join("".join(char for char in unicodedata.normalize("NFKD", text.casefold())
                           if not unicodedata.combining(char)).split()).strip(" !.,?;")


def is_opt_out(text):
    normalized = normalize_text(text)
    return normalized in {"sair", "stop", "pare", "parar", "cancelar", "nao", "nao tenho interesse"} or any(
        phrase in normalized for phrase in ["nao tenho interesse", "nao quero receber", "nao quero esse contato",
                                           "nao me mande", "nao me envie", "pare de mandar", "pare de enviar",
                                           "remova meu numero", "exclua meu contato", "me tire da lista"])


def human_reason(text):
    normalized = normalize_text(text)
    if any(word in normalized for word in ["humano", "atendente", "responsavel", "uma pessoa", "me liga", "me ligue"]):
        return "pediu_responsavel"
    if any(word in normalized for word in ["preco", "quanto custa", "valor", "contrato", "contratar", "orcamento"]):
        return "proposta_ou_preco"
    if any(word in normalized for word in ["demonstracao", "quero conhecer", "quero ver", "quero testar", "tenho interesse"]):
        return "interesse_demonstracao"
    return None


def timestamp(value):
    try:
        result = datetime.fromtimestamp(float(value), timezone.utc)
        if result > utcnow() + timedelta(minutes=5) or result < utcnow() - timedelta(days=365):
            return None
        return result
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def recipient(value):
    return "+" + value if isinstance(value, str) and re.fullmatch(r"\d{10,15}", value) else None


def array_field(value, name):
    items = value.get(name, []) if isinstance(value, dict) else []
    return items if isinstance(items, list) else []


def _opt_out(service, session, conversation, inbound):
    ids = list(session.scalars(select(Lead.id).where(Lead.whatsapp_recipient == conversation.recipient)))
    if conversation.lead_id and conversation.lead_id not in ids:
        ids.append(conversation.lead_id)
    for lead_id in sorted(ids):
        lead = session.scalar(select(Lead).where(Lead.id == lead_id).with_for_update())
        if lead.whatsapp_recipient and lead.whatsapp_recipient != conversation.recipient:
            # O pedido deste número não revoga autorização registrada para outro.
            continue
        latest = session.scalar(select(ConsentEvent).where(ConsentEvent.lead_id == lead_id)
            .order_by(ConsentEvent.occurred_at.desc()).limit(1))
        if latest and latest.status == "concedido" and as_utc(latest.occurred_at) > as_utc(inbound.occurred_at):
            # Não reaplica um pedido antigo depois de nova autorização explícita.
            continue
        if lead.consent_status != "revogado":
            session.add(ConsentEvent(lead_id=lead.id, status="revogado", recipient=conversation.recipient,
                evidence=f"Pedido de interrupção recebido por webhook assinado. Mensagem {inbound.provider_message_id}: {inbound.text[:800]}",
                occurred_at=inbound.occurred_at))
        lead.consent_status, lead.whatsapp_recipient = "revogado", None
    current_lead = session.get(Lead, conversation.lead_id) if conversation.lead_id else None
    if current_lead and current_lead.consent_status == "concedido" and current_lead.whatsapp_recipient == conversation.recipient:
        return
    if not conversation.opted_out_at or as_utc(inbound.occurred_at) > as_utc(conversation.opted_out_at):
        conversation.opted_out_at = inbound.occurred_at
    conversation.paused, conversation.pause_reason = True, "pedido_interrupcao"
    service.cancel_pending(session, conversation.id)


def receive_webhook(service, payload):
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        return {"mensagens_registradas": 0, "status_registrados": 0}
    messages_count, statuses_count = 0, 0
    for entry in array_field(payload, "entry"):
        if not isinstance(entry, dict):
            continue
        for change in array_field(entry, "changes"):
            value = change.get("value", {}) if isinstance(change, dict) else {}
            metadata = value.get("metadata", {}) if isinstance(value, dict) else {}
            if not isinstance(metadata, dict) or str(metadata.get("phone_number_id", "")) != service.settings.whatsapp_phone_number_id:
                continue
            for raw in array_field(value, "messages"):
                if not isinstance(raw, dict):
                    continue
                phone, occurred = recipient(raw.get("from")), timestamp(raw.get("timestamp"))
                remote_id = raw.get("id")
                if not phone or not occurred or not isinstance(remote_id, str) or not 1 <= len(remote_id) <= 250:
                    continue
                kind = "text" if raw.get("type") == "text" else "midia"
                text_object = raw.get("text", {})
                text = text_object.get("body", "") if kind == "text" and isinstance(text_object, dict) else "[Mensagem de mídia recebida]"
                if not isinstance(text, str) or not text.strip():
                    continue
                with service.sessions() as session:
                    if session.scalar(select(CommercialMessage.id).where(CommercialMessage.provider_message_id == remote_id)):
                        continue
                    existing = session.scalar(select(CommercialConversation).where(CommercialConversation.recipient == phone))
                    lead = session.get(Lead, existing.lead_id) if existing and existing.lead_id else session.scalar(
                        select(Lead).where(Lead.whatsapp_recipient == phone).order_by(Lead.priority.desc(), Lead.id).limit(1))
                    # Ordem de locks igual à do envio: empresa antes da conversa.
                    ids = list(session.scalars(select(Lead.id).where(Lead.whatsapp_recipient == phone)))
                    if lead and lead.id not in ids:
                        ids.append(lead.id)
                    for identifier in sorted(ids):
                        session.scalar(select(Lead).where(Lead.id == identifier).with_for_update())
                    conversation = service._conversation(session, phone, lead.id if lead else None)
                    inserted = session.execute(db_insert(session, CommercialMessage).values(
                        lead_id=conversation.lead_id, conversation_id=conversation.id, recipient=phone,
                        direction="entrada", kind=kind, purpose="mensagem_cliente", text=text[:8000],
                        status="recebida", provider_message_id=remote_id, occurred_at=occurred)
                        .on_conflict_do_nothing(index_elements=["provider_message_id"])
                        .returning(CommercialMessage.id)).scalar_one_or_none()
                    if not inserted:
                        session.rollback()
                        continue
                    inbound = session.get(CommercialMessage, inserted)
                    if not conversation.last_inbound_at or occurred >= as_utc(conversation.last_inbound_at):
                        conversation.last_inbound_at, conversation.last_inbound_id = occurred, inbound.id
                    if is_opt_out(text):
                        _opt_out(service, session, conversation, inbound)
                        inbound.status = "processada"
                    session.commit()
                    messages_count += 1
            for raw in array_field(value, "statuses"):
                if not isinstance(raw, dict) or raw.get("status") not in {"sent", "delivered", "read", "failed"}:
                    continue
                phone, occurred = recipient(raw.get("recipient_id")), timestamp(raw.get("timestamp"))
                remote_id = raw.get("id")
                if not phone or not occurred or not isinstance(remote_id, str) or not 1 <= len(remote_id) <= 250:
                    continue
                errors = array_field(raw, "errors")
                code = str(errors[0].get("code", "")) if errors and isinstance(errors[0], dict) else ""
                code = code if re.fullmatch(r"\d{1,20}", code) else None
                with service.sessions() as session:
                    result = session.execute(db_insert(session, WhatsAppStatusEvent).values(
                        provider_message_id=remote_id, recipient=phone, status=raw["status"],
                        occurred_at=occurred, error_code=code).on_conflict_do_nothing(
                            index_elements=["provider_message_id", "status", "occurred_at"]))
                    message = session.scalar(select(CommercialMessage).where(
                        CommercialMessage.provider_message_id == remote_id, CommercialMessage.direction == "saida").with_for_update())
                    if message:
                        service.apply_delivery(session, message)
                    session.commit()
                    statuses_count += result.rowcount
    return {"mensagens_registradas": messages_count, "status_registrados": statuses_count}


def process_inbound(service):
    if not service.settings.whatsapp_ready:
        return 0
    now = utcnow()
    with service.sessions() as session:
        session.execute(update(CommercialMessage).where(CommercialMessage.status == "em_analise",
            CommercialMessage.processing_at < now - timedelta(minutes=3)).values(status="recebida", processing_at=None))
        identifier = session.scalar(select(CommercialMessage.id).where(CommercialMessage.direction == "entrada",
            CommercialMessage.status == "recebida").order_by(CommercialMessage.created_at, CommercialMessage.id).limit(1))
        if not identifier:
            session.commit()
            return 0
        claimed = session.execute(update(CommercialMessage).where(CommercialMessage.id == identifier,
            CommercialMessage.status == "recebida").values(status="em_analise", processing_at=now))
        session.commit()
        if claimed.rowcount != 1:
            return 0
    with service.sessions() as session:
        inbound = session.get(CommercialMessage, identifier)
        lead_id = session.scalar(select(CommercialConversation.lead_id).where(
            CommercialConversation.id == inbound.conversation_id))
        lead = session.scalar(select(Lead).where(Lead.id == lead_id).with_for_update()) if lead_id else None
        conversation = session.scalar(select(CommercialConversation).where(
            CommercialConversation.id == inbound.conversation_id).with_for_update())
        if conversation.last_inbound_id != inbound.id or conversation.paused or conversation.opted_out_at:
            inbound.status = "processada"
            session.commit()
            return 1
        if not service._lead_allowed(lead) or lead.whatsapp_recipient != conversation.recipient:
            service.handoff(session, conversation, inbound, "contato_sem_autorizacao_ou_vinculo")
            inbound.status = "processada"
            session.commit()
            return 1
        if as_utc(inbound.occurred_at) + timedelta(hours=24) <= now:
            service.handoff(session, conversation, inbound, "janela_resposta_encerrada")
            inbound.status = "processada"
            session.commit()
            return 1
        reason = human_reason(inbound.text)
        if inbound.kind != "text":
            reason = "mensagem_de_midia"
        if conversation.auto_replies >= service.settings.commercial_max_auto_replies:
            reason = "limite_conversa_automatica"
        if not service.settings.commercial_auto_reply:
            reason = "atendimento_manual"
        history = [{"direcao": item.direction, "texto": item.text[:1200]} for item in reversed(session.scalars(
            select(CommercialMessage).where(CommercialMessage.conversation_id == conversation.id,
                CommercialMessage.id != inbound.id).order_by(CommercialMessage.created_at.desc()).limit(8)).all())]
        lead_id, current_text = lead.id, inbound.text
    if reason:
        decision, engine = None, "regras_comerciais"
    else:
        # A chamada de IA ocorre fora da transação e fora do recebimento do webhook.
        with service.sessions() as session:
            lead = session.get(Lead, lead_id)
            decision, engine = decide_reply(service.settings, lead, current_text, history, service.ai_transport)
        if decision.acao == "encaminhar":
            reason = "falha_ia" if engine == "falha_ia" else "avaliacao_responsavel"
    with service.sessions() as session:
        lead = session.scalar(select(Lead).where(Lead.id == lead_id).with_for_update())
        inbound = session.get(CommercialMessage, identifier)
        conversation = session.scalar(select(CommercialConversation).where(
            CommercialConversation.id == inbound.conversation_id).with_for_update())
        existing_reply = session.scalar(select(CommercialMessage.id).where(CommercialMessage.reply_to_id == inbound.id))
        allowed = (service._lead_allowed(lead) and lead.whatsapp_recipient == conversation.recipient
                   and not conversation.paused and not conversation.opted_out_at
                   and conversation.last_inbound_id == inbound.id)
        if allowed and not existing_reply:
            if reason:
                service.handoff(session, conversation, inbound, reason)
                if service.settings.commercial_auto_reply:
                    from .commercial import HANDOFF_REPLY
                    service.add_reply(session, conversation, inbound, HANDOFF_REPLY, engine, handoff=True)
            else:
                service.add_reply(session, conversation, inbound, decision.texto, engine)
        inbound.status = "processada"
        session.commit()
    return 1
