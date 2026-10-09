"""Fila comercial persistente; permissões verificadas novamente antes de enviar."""
from datetime import datetime, timedelta, timezone
import hashlib
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .catalog import resolve_city
from .models import (CommercialConversation, CommercialHandoff, CommercialMessage,
                     CommercialQuota, ConsentEvent, Lead, WhatsAppStatusEvent, as_utc, utcnow)
from .service import db_insert, eligible_for_commercial
from .whatsapp import WhatsAppClient, WhatsAppRejected, WhatsAppUncertain


OPENING_TEMPLATE = (
    "Olá, {{1}}! Aqui é da Nelvo Company. Você autorizou nosso contato sobre atendimento "
    "por IA para WhatsApp e sites. Posso te apresentar uma demonstração? "
    "Se preferir não receber mensagens, responda SAIR."
)
HANDOFF_REPLY = "Estou encaminhando seu contato para um responsável dar continuidade ao atendimento."
BUSINESS_TIMEZONE = ZoneInfo("America/Sao_Paulo")


class CommercialError(Exception):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


def message_data(message):
    return {"id": message.id, "empresa_id": message.lead_id, "conversa_id": message.conversation_id,
            "destinatario": message.recipient, "direcao": message.direction, "tipo": message.kind,
            "finalidade": message.purpose, "texto": message.text, "payload_whatsapp": message.payload,
            "status": message.status, "entrega": message.delivery_status,
            "id_whatsapp": message.provider_message_id, "modo": message.engine,
            "tentativas": message.attempts, "erro": message.error,
            "disponivel_em": as_utc(message.available_at).isoformat(),
            "criada_em": as_utc(message.created_at).isoformat(),
            "enviada_em": as_utc(message.sent_at).isoformat() if message.sent_at else None}


def conversation_data(conversation):
    return {"id": conversation.id, "empresa_id": conversation.lead_id, "destinatario": conversation.recipient,
            "ia_pausada": conversation.paused, "motivo_pausa": conversation.pause_reason,
            "contato_interrompido": conversation.opted_out_at is not None,
            "ultima_mensagem_cliente_em": as_utc(conversation.last_inbound_at).isoformat() if conversation.last_inbound_at else None,
            "respostas_automaticas": conversation.auto_replies}


class CommercialService:
    def __init__(self, sessions, settings, whatsapp_transport=None, ai_transport=None):
        self.sessions, self.settings, self.ai_transport = sessions, settings, ai_transport
        self.client = WhatsAppClient(settings, whatsapp_transport)

    def status(self):
        day = utcnow().astimezone(BUSINESS_TIMEZONE).date()
        with self.sessions() as session:
            quota = session.get(CommercialQuota, day)
            queued = session.scalar(select(func.count()).select_from(CommercialMessage).where(CommercialMessage.status == "na_fila"))
        return {"envio_ativo": self.settings.whatsapp_ready,
                "habilitado": self.settings.whatsapp_enabled,
                "variaveis_pendentes": self.settings.whatsapp_missing(),
                "ia_configurada": self.settings.ai_configured,
                "respostas_automaticas": self.settings.commercial_auto_reply,
                "limite_diario_abordagens": self.settings.commercial_daily_limit,
                "abordagens_tentadas_hoje": quota.opening_attempts if quota else 0,
                "fuso_limite_diario": "America/Sao_Paulo", "mensagens_na_fila": queued,
                "template": {"nome": self.settings.whatsapp_template_name,
                             "idioma": self.settings.whatsapp_template_language,
                             "texto_para_cadastrar_na_meta": OPENING_TEMPLATE,
                             "parametros_body": 1}}

    def _get(self, session, model, identifier, label, lock=False):
        query = select(model).where(model.id == identifier)
        if lock:
            query = query.with_for_update()
        row = session.scalar(query)
        if row is None:
            raise CommercialError(f"{label} não encontrada.", 404)
        return row

    @staticmethod
    def _lead_allowed(lead):
        if not lead or not eligible_for_commercial(lead):
            return False
        try:
            city = resolve_city(lead.city)
        except ValueError:
            return False
        return lead.city_ibge == city.ibge_code

    def _conversation(self, session, recipient, lead_id=None):
        session.execute(db_insert(session, CommercialConversation).values(
            recipient=recipient, lead_id=lead_id).on_conflict_do_nothing(index_elements=["recipient"]))
        conversation = session.scalar(select(CommercialConversation).where(
            CommercialConversation.recipient == recipient).with_for_update())
        if lead_id and conversation.lead_id and conversation.lead_id != lead_id:
            raise CommercialError("Esse destinatário já possui uma conversa vinculada a outra empresa.")
        if lead_id and not conversation.lead_id:
            conversation.lead_id = lead_id
        return conversation

    def draft(self, lead_id):
        with self.sessions() as session:
            lead = self._get(session, Lead, lead_id, "Empresa")
            name = " ".join(lead.name.split())[:200]
            recipient = lead.whatsapp_recipient or lead.phone_normalized
            payload = {"messaging_product": "whatsapp", "recipient_type": "individual",
                       "to": recipient.lstrip("+") if recipient else "",
                       "type": "template", "template": {"name": self.settings.whatsapp_template_name,
                       "language": {"code": self.settings.whatsapp_template_language},
                       "components": [{"type": "body", "parameters": [{"type": "text", "text": name}]}]}}
            message = CommercialMessage(lead_id=lead.id, recipient=recipient, direction="saida",
                                        kind="template", purpose="apresentacao", payload=payload,
                                        text=OPENING_TEMPLATE.replace("{{1}}", name), status="rascunho",
                                        engine="template_comercial")
            session.add(message)
            session.commit()
            return message_data(message)

    def review(self, message_id, approved):
        with self.sessions() as session:
            message = self._get(session, CommercialMessage, message_id, "Mensagem", lock=True)
            if message.direction != "saida" or message.status not in {"rascunho", "aprovada"}:
                raise CommercialError("Somente rascunhos ainda não enfileirados podem ser revisados.")
            message.status = "aprovada" if approved else "descartada"
            message.approved_at = utcnow() if approved else None
            session.commit()
            return message_data(message)

    def enqueue(self, message_id):
        if not self.settings.whatsapp_ready:
            raise CommercialError("Configure as variáveis do WhatsApp e WHATSAPP_ENABLED=true antes de enfileirar.")
        try:
            with self.sessions() as session:
                message = self._get(session, CommercialMessage, message_id, "Mensagem", lock=True)
                if message.status in {"na_fila", "processando", "aceita", "envio_incerto", "falhou", "bloqueada"}:
                    return message_data(message)
                if message.status != "aprovada" or message.kind != "template" or not message.approved_at:
                    raise CommercialError("A mensagem inicial precisa de revisão e aprovação.")
                lead = self._get(session, Lead, message.lead_id, "Empresa", lock=True)
                if not self._lead_allowed(lead):
                    raise CommercialError("A empresa precisa ser real, aprovada e ter consentimento registrado.")
                if message.recipient != lead.whatsapp_recipient:
                    raise CommercialError("O destinatário autorizado mudou. Prepare e revise um novo rascunho.")
                conversation = self._conversation(session, message.recipient, lead.id)
                if conversation.opted_out_at or conversation.paused:
                    raise CommercialError("A conversa está interrompida ou pausada para atendimento humano.")
                message.conversation_id = conversation.id
                message.sender_id = self.settings.whatsapp_phone_number_id
                message.opening_key = hashlib.sha256(message.recipient.encode()).hexdigest()
                message.status, message.available_at = "na_fila", utcnow()
                session.commit()
                return message_data(message)
        except IntegrityError:
            raise CommercialError("Já existe uma abordagem inicial para esse destinatário; não foi criado outro envio.") from None

    def cancel(self, message_id):
        with self.sessions() as session:
            message = self._get(session, CommercialMessage, message_id, "Mensagem", lock=True)
            safe_failed = message.status == "falhou" and not message.provider_message_id
            safe_blocked = message.status == "bloqueada" and message.attempts == 0
            if message.status not in {"rascunho", "aprovada", "na_fila", "cancelada"} and not safe_failed and not safe_blocked:
                raise CommercialError("O envio já começou ou terminou; não pode ser cancelado retroativamente.")
            message.status = "cancelada"
            if message.attempts == 0 or safe_failed:
                message.opening_key = None
            session.commit()
            return message_data(message)

    def pause(self, conversation_id, paused):
        with self.sessions() as session:
            conversation = self._get(session, CommercialConversation, conversation_id, "Conversa", lock=True)
            if not paused:
                lead = session.get(Lead, conversation.lead_id) if conversation.lead_id else None
                if not self._lead_allowed(lead) or lead.whatsapp_recipient != conversation.recipient:
                    raise CommercialError("Reativação exige empresa aprovada e consentimento para o destinatário atual.")
                if conversation.opted_out_at:
                    latest = session.scalar(select(ConsentEvent).where(ConsentEvent.lead_id == lead.id,
                        ConsentEvent.status == "concedido", ConsentEvent.recipient == conversation.recipient)
                        .order_by(ConsentEvent.occurred_at.desc()).limit(1))
                    if not latest or as_utc(latest.occurred_at) <= as_utc(conversation.opted_out_at):
                        raise CommercialError("Registre uma nova autorização posterior ao pedido de interrupção.")
                    conversation.opted_out_at = None
                conversation.auto_replies = 0
                for ticket in session.scalars(select(CommercialHandoff).where(
                        CommercialHandoff.conversation_id == conversation.id, CommercialHandoff.status == "aberto")):
                    ticket.status, ticket.closed_at = "resolvido", utcnow()
            conversation.paused = paused
            conversation.pause_reason = "pausa_operador" if paused else None
            if paused:
                self.cancel_pending(session, conversation.id)
            session.commit()
            return conversation_data(conversation)

    @staticmethod
    def cancel_pending(session, conversation_id):
        session.execute(update(CommercialMessage).where(CommercialMessage.conversation_id == conversation_id,
            CommercialMessage.direction == "saida", CommercialMessage.status == "na_fila")
            .values(status="cancelada", error="Conversa pausada ou contato interrompido."))

    def handoff(self, session, conversation, inbound, reason):
        ticket = session.scalar(select(CommercialHandoff).where(
            CommercialHandoff.conversation_id == conversation.id, CommercialHandoff.status == "aberto"))
        if ticket is None:
            ticket = CommercialHandoff(conversation_id=conversation.id, reason=reason,
                                       summary=f"Motivo: {reason}. Última mensagem: {inbound.text[:1600]}")
            session.add(ticket)
        self.cancel_pending(session, conversation.id)
        conversation.paused, conversation.pause_reason = True, reason
        return ticket

    def add_reply(self, session, conversation, inbound, text, engine, handoff=False):
        message = CommercialMessage(lead_id=conversation.lead_id, conversation_id=conversation.id,
            recipient=conversation.recipient, sender_id=self.settings.whatsapp_phone_number_id,
            direction="saida", kind="text", purpose="encaminhamento" if handoff else "resposta_automatica",
            text=text, engine=engine, status="na_fila", approved_at=utcnow(), reply_to_id=inbound.id,
            payload={"messaging_product": "whatsapp", "recipient_type": "individual",
                     "to": conversation.recipient.lstrip("+"), "type": "text",
                     "text": {"preview_url": False, "body": text}})
        session.add(message)
        if not handoff:
            conversation.auto_replies += 1

    def _send_block_reason(self, session, message):
        lead = session.get(Lead, message.lead_id) if message.lead_id else None
        if not self._lead_allowed(lead) or lead.whatsapp_recipient != message.recipient:
            return "Revisão, consentimento ou destinatário deixaram de permitir o contato."
        conversation = session.get(CommercialConversation, message.conversation_id)
        if not conversation or conversation.opted_out_at:
            return "Conversa inexistente ou contato interrompido."
        if conversation.paused and message.purpose != "encaminhamento":
            return "Conversa assumida pelo atendimento humano."
        if message.sender_id != self.settings.whatsapp_phone_number_id:
            return "O número de envio foi alterado; revise a mensagem com a configuração atual."
        if message.kind == "text" and (not conversation.last_inbound_at or
                as_utc(conversation.last_inbound_at) + timedelta(hours=24) <= utcnow()):
            return "A janela de resposta de 24 horas encerrou."
        if message.purpose == "resposta_automatica" and message.reply_to_id != conversation.last_inbound_id:
            return "A conversa recebeu uma nova mensagem; a resposta anterior foi cancelada."
        return None

    def apply_delivery(self, session, message):
        if not message.provider_message_id:
            return
        ranking = {None: 0, "sent": 1, "delivered": 2, "read": 3}
        events = session.scalars(select(WhatsAppStatusEvent).where(
            WhatsAppStatusEvent.provider_message_id == message.provider_message_id,
            WhatsAppStatusEvent.recipient == message.recipient).order_by(WhatsAppStatusEvent.occurred_at)).all()
        for event in events:
            if event.status == "failed":
                if message.delivery_status not in {"delivered", "read"}:
                    message.delivery_status, message.status = "failed", "falhou"
                    message.error = "Meta informou falha na entrega, código " + (event.error_code or "não informado") + "."
            elif ranking.get(event.status, 0) > ranking.get(message.delivery_status, 0):
                message.delivery_status = event.status
                if message.status == "falhou":
                    message.status, message.error = "aceita", None

    def process_outbound(self):
        if not self.settings.whatsapp_ready:
            return 0
        now = utcnow()
        with self.sessions() as session:
            # Um processo encerrado pode ter enviado a mensagem sem salvar a confirmação.
            session.execute(update(CommercialMessage).where(CommercialMessage.status == "processando",
                CommercialMessage.processing_at < now - timedelta(minutes=3)).values(
                    status="envio_incerto", error="Processamento interrompido. Não houve reenvio automático."))
            message_id = session.scalar(select(CommercialMessage.id).where(
                CommercialMessage.status == "na_fila", CommercialMessage.available_at <= now)
                .order_by(CommercialMessage.created_at, CommercialMessage.id).limit(1))
            if not message_id:
                session.commit()
                return 0
            claimed = session.execute(update(CommercialMessage).where(CommercialMessage.id == message_id,
                CommercialMessage.status == "na_fila").values(status="processando", processing_at=now))
            session.commit()
            if claimed.rowcount != 1:
                return 0
        # O lock da empresa serializa este envio com alteração de consentimento.
        with self.sessions() as session:
            message = session.get(CommercialMessage, message_id)
            if message.lead_id:
                session.scalar(select(Lead).where(Lead.id == message.lead_id).with_for_update())
            if message.conversation_id:
                session.scalar(select(CommercialConversation).where(
                    CommercialConversation.id == message.conversation_id).with_for_update())
            reason = self._send_block_reason(session, message)
            if reason:
                message.status, message.error = "bloqueada", reason
                session.commit()
                return 1
            if message.kind == "template":
                local = now.astimezone(BUSINESS_TIMEZONE)
                session.execute(db_insert(session, CommercialQuota).values(day=local.date(), opening_attempts=0)
                    .on_conflict_do_nothing(index_elements=["day"]))
                reserved = session.execute(update(CommercialQuota).where(CommercialQuota.day == local.date(),
                    CommercialQuota.opening_attempts < self.settings.commercial_daily_limit)
                    .values(opening_attempts=CommercialQuota.opening_attempts + 1))
                if reserved.rowcount != 1:
                    next_day = datetime.combine(local.date() + timedelta(days=1), datetime.min.time(), BUSINESS_TIMEZONE)
                    message.status, message.available_at, message.processing_at = "na_fila", next_day.astimezone(timezone.utc), None
                    session.commit()
                    return 0
            message.attempts += 1
            # Reserva diária e tentativa ficam duráveis antes da chamada externa.
            session.commit()
        with self.sessions() as session:
            message = session.get(CommercialMessage, message_id)
            if message.lead_id:
                session.scalar(select(Lead).where(Lead.id == message.lead_id).with_for_update())
            if message.conversation_id:
                session.scalar(select(CommercialConversation).where(
                    CommercialConversation.id == message.conversation_id).with_for_update())
            reason = self._send_block_reason(session, message)
            if reason:
                message.status, message.error = "bloqueada", reason
                session.commit()
                return 1
            try:
                message.provider_message_id = self.client.send(message.payload)
                message.status, message.sent_at = "aceita", utcnow()
                self.apply_delivery(session, message)
            except WhatsAppRejected as error:
                message.status, message.error = "falhou", str(error)
            except WhatsAppUncertain as error:
                message.status, message.error = "envio_incerto", str(error)
            session.commit()
            return 1

    def receive(self, payload):
        from .commercial_inbox import receive_webhook
        return receive_webhook(self, payload)

    def process_cycle(self):
        from .commercial_inbox import process_inbound
        return {"entradas_processadas": process_inbound(self), "envios_processados": self.process_outbound()}
