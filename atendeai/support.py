"""Empresas, sessões privadas de visitantes, base de respostas e chamados."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import secrets

from sqlalchemy import func, select, update

from .commercial import BUSINESS_TIMEZONE, CommercialError
from .commercial_inbox import normalize_text
from .models import (SupportConversation, SupportHandoff, SupportKnowledge, SupportMessage,
                     SupportQuota, SupportTenant, as_utc, utcnow)
from .service import db_insert
from .support_brain import SupportDecision, decide_support, select_knowledge
from .support_policy import (ASK_HANDOFF, CONFIRMATION_PREFIX, DECLINE_HANDOFF,
                             abusive_message, clearly_unrelated_message,
                             confirmation_reply, explicit_human_request)


DEMO_TENANT_ID = "00000000-0000-4000-a000-000000000003"
DEMO_SITE_KEY = "atendeai-demonstracao-publica"
DEMO_ORIGIN = "https://atendeai-co.squareweb.app"

SUPPORT_HANDOFF = "Estou encaminhando seu chamado para um responsável dar continuidade ao atendimento."


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def support_message_data(row, private=False):
    result = {"id": row.id, "direcao": row.direction, "autor": row.author, "texto": row.text,
              "status": row.status, "modo": row.engine, "entrega": row.delivery_status,
              "criada_em": as_utc(row.created_at).isoformat()}
    if private:
        result.update(empresa_id=row.tenant_id, conversa_id=row.conversation_id,
                      id_whatsapp=row.provider_message_id, erro=row.error, tentativas=row.attempts)
    return result


def support_conversation_data(row, private=False):
    result = {"id": row.id, "empresa_id": row.tenant_id, "canal": row.channel, "estado": row.state,
              "motivo_pausa": row.pause_reason, "criada_em": as_utc(row.created_at).isoformat(),
              "aguardando_confirmacao": bool(row.pause_reason and row.pause_reason.startswith(CONFIRMATION_PREFIX))}
    if private:
        result["contato"] = row.recipient if row.channel == "whatsapp" else None
    return result


class SupportService:
    def __init__(self, sessions, settings, whatsapp_transport=None, ai_transport=None):
        self.sessions, self.settings = sessions, settings
        self.whatsapp_transport, self.ai_transport = whatsapp_transport, ai_transport

    def ensure_demo(self):
        """Demonstração pública separada, sem IA paga ou conta WhatsApp."""
        with self.sessions() as session:
            session.execute(db_insert(session, SupportTenant).values(
                id=DEMO_TENANT_ID, name="AtendeAI — Demonstração", site_key_hash=digest(DEMO_SITE_KEY),
                allowed_origins=[DEMO_ORIGIN],
                welcome_text="Olá! Esta é uma demonstração do atendimento da AtendeAI. Pergunte quais serviços oferecemos ou como funciona o encaminhamento para uma pessoa.",
                active=True, ai_enabled=False, daily_conversation_limit=100, daily_ai_limit=100)
                .on_conflict_do_nothing(index_elements=["id"]))
            examples = [
                ("00000000-0000-4000-a000-000000000031", "Serviços da AtendeAI",
                 "A proposta da AtendeAI é automatizar o atendimento por site e WhatsApp, organizar as conversas e encaminhar dúvidas para uma pessoa quando necessário. O WhatsApp depende da configuração oficial da conta."),
                ("00000000-0000-4000-a000-000000000032", "Encaminhamento para uma pessoa",
                 "Quando o assistente precisa de uma pessoa, registra um chamado com histórico e pausa as respostas automáticas. O responsável acompanha a fila e responde na mesma conversa."),
                ("00000000-0000-4000-a000-000000000033", "Como funciona no WhatsApp",
                 "O atendimento pelo WhatsApp usa a API oficial da Meta e a conta autorizada de cada empresa. Esta demonstração funciona pelo site; nenhum número real do WhatsApp está conectado nela."),
            ]
            for identifier, title, content in examples:
                session.execute(db_insert(session, SupportKnowledge).values(id=identifier, tenant_id=DEMO_TENANT_ID,
                    title=title, content=content, active=True).on_conflict_do_nothing(index_elements=["id"]))
            session.commit()

    @staticmethod
    def tenant(session, identifier, active=False, lock=False):
        query = select(SupportTenant).where(SupportTenant.id == identifier)
        row = session.scalar(query.with_for_update() if lock else query)
        if not row or (active and not row.active):
            raise CommercialError("Empresa de atendimento não encontrada ou desativada.", 404)
        return row

    @staticmethod
    def conversation(session, tenant_id, identifier, lock=False):
        query = select(SupportConversation).where(SupportConversation.id == identifier,
                                                 SupportConversation.tenant_id == tenant_id)
        row = session.scalar(query.with_for_update() if lock else query)
        if not row:
            raise CommercialError("Conversa não encontrada nesta empresa.", 404)
        return row

    def account_settings(self, tenant_id):
        account = self.settings.support_whatsapp_accounts.get(tenant_id, {})
        return replace(self.settings, whatsapp_enabled=account.get("enabled", False),
            whatsapp_token=account.get("token", ""), whatsapp_phone_number_id=account.get("phone_number_id", ""),
            whatsapp_app_secret=account.get("app_secret", ""), whatsapp_verify_token=account.get("verify_token", ""),
            whatsapp_api_version=account.get("api_version", "v24.0"))

    def tenant_data(self, row):
        account = self.account_settings(row.id)
        return {"id": row.id, "nome": row.name, "origens_permitidas": row.allowed_origins,
                "boas_vindas": row.welcome_text, "ativa": row.active, "ia_habilitada": row.ai_enabled,
                "ia_configurada": self.settings.ai_configured, "ia_provedor": self.settings.ai_provider,
                "ia_modelo": self.settings.local_ai_model if self.settings.ai_configured else None,
                "whatsapp_ativo": account.whatsapp_ready,
                "limite_conversas_dia": row.daily_conversation_limit, "limite_ia_dia": row.daily_ai_limit}

    def create_tenant(self, body):
        key = secrets.token_urlsafe(32)
        with self.sessions() as session:
            row = SupportTenant(name=body.nome, allowed_origins=body.origens_permitidas,
                welcome_text=body.boas_vindas, site_key_hash=digest(key), ai_enabled=body.ia_habilitada,
                daily_conversation_limit=body.limite_conversas_dia, daily_ai_limit=body.limite_ia_dia)
            session.add(row)
            session.commit()
            return {**self.tenant_data(row), "chave_site": key}

    @staticmethod
    def origin_allowed(tenant, origin):
        if not origin or origin not in tenant.allowed_origins:
            raise CommercialError("Origem do site não autorizada para esta empresa.", 403)

    def site_conversation(self, tenant_id, key, origin):
        with self.sessions() as session:
            tenant = self.tenant(session, tenant_id, active=True)
            self.origin_allowed(tenant, origin)
            if not key or not secrets.compare_digest(digest(key), tenant.site_key_hash):
                raise CommercialError("Chave do site inválida.", 401)
            if not self.reserve(session, tenant, "conversations_opened", tenant.daily_conversation_limit):
                raise CommercialError("Limite diário de novas conversas atingido.", 429)
            token = secrets.token_urlsafe(32)
            conversation = SupportConversation(tenant_id=tenant.id, channel="site", token_hash=digest(token), origin=origin)
            session.add(conversation)
            session.flush()
            session.add(SupportMessage(tenant_id=tenant.id, conversation_id=conversation.id,
                direction="saida", author="sistema", text=tenant.welcome_text, status="disponivel", engine="boas_vindas"))
            session.commit()
            return {"conversa": support_conversation_data(conversation), "token_conversa": token,
                    "boas_vindas": tenant.welcome_text}

    def visitor_access(self, session, tenant_id, conversation_id, token, origin, lock=False):
        tenant = self.tenant(session, tenant_id, active=True)
        self.origin_allowed(tenant, origin)
        conversation = self.conversation(session, tenant_id, conversation_id, lock=lock)
        if conversation.channel != "site" or not token or not conversation.token_hash or not secrets.compare_digest(
                digest(token), conversation.token_hash):
            raise CommercialError("Token da conversa inválido.", 401)
        if origin != conversation.origin:
            raise CommercialError("A conversa pertence a outra origem.", 403)
        return conversation

    def site_message(self, tenant_id, conversation_id, token, origin, text, client_id):
        with self.sessions() as session:
            conversation = self.visitor_access(session, tenant_id, conversation_id, token, origin, lock=True)
            previous = session.scalar(select(SupportMessage).where(SupportMessage.conversation_id == conversation.id,
                                                                  SupportMessage.client_message_id == client_id))
            if previous:
                if previous.text != text:
                    raise CommercialError("Este id_cliente já foi usado para outro texto.")
                return support_message_data(previous)
            count = session.scalar(select(func.count()).select_from(SupportMessage).where(
                SupportMessage.conversation_id == conversation.id, SupportMessage.direction == "entrada"))
            if count >= 50:
                raise CommercialError("Limite de mensagens desta conversa atingido; continue com o responsável.", 429)
            if conversation.state == "interrompida":
                raise CommercialError("A conversa foi interrompida.")
            message = SupportMessage(tenant_id=tenant_id, conversation_id=conversation.id, direction="entrada",
                author="cliente", text=text, client_message_id=client_id, status="recebida")
            session.add(message)
            session.flush()
            conversation.last_inbound_at, conversation.last_inbound_id = message.occurred_at, message.id
            session.commit()
            return support_message_data(message)

    @staticmethod
    def reserve(session, tenant, field, limit):
        day = utcnow().astimezone(BUSINESS_TIMEZONE).date()
        session.execute(db_insert(session, SupportQuota).values(tenant_id=tenant.id, day=day,
            conversations_opened=0, ai_calls=0).on_conflict_do_nothing(index_elements=["tenant_id", "day"]))
        column = getattr(SupportQuota, field)
        result = session.execute(update(SupportQuota).where(SupportQuota.tenant_id == tenant.id,
            SupportQuota.day == day, column < limit).values({field: column + 1}))
        return result.rowcount == 1

    @staticmethod
    def cancel_pending(session, conversation_id):
        session.execute(update(SupportMessage).where(SupportMessage.conversation_id == conversation_id,
            SupportMessage.direction == "saida", SupportMessage.status == "na_fila",
            SupportMessage.author != "humano").values(status="cancelada", error="Atendimento assumido por uma pessoa."))

    def handoff(self, session, conversation, inbound, reason):
        ticket = session.scalar(select(SupportHandoff).where(SupportHandoff.conversation_id == conversation.id,
                                                           SupportHandoff.status == "aberto"))
        if not ticket:
            ticket = SupportHandoff(tenant_id=conversation.tenant_id, conversation_id=conversation.id,
                reason=reason, summary=f"Motivo: {reason}. Última mensagem: {inbound.text[:1600]}")
            session.add(ticket)
        self.cancel_pending(session, conversation.id)
        conversation.state, conversation.pause_reason = "humano", reason

    def add_reply(self, session, conversation, text, author, inbound=None, engine=None):
        account = self.account_settings(conversation.tenant_id)
        row = SupportMessage(tenant_id=conversation.tenant_id, conversation_id=conversation.id,
            direction="saida", author=author, text=text, engine=engine,
            reply_to_id=inbound.id if inbound else None,
            sender_id=account.whatsapp_phone_number_id if conversation.channel == "whatsapp" else None,
            status="na_fila" if conversation.channel == "whatsapp" else "disponivel")
        session.add(row)
        if author == "assistente":
            conversation.auto_replies += 1
        return row

    def human_reply(self, tenant_id, conversation_id, text):
        with self.sessions() as session:
            self.tenant(session, tenant_id, active=True)
            conversation = self.conversation(session, tenant_id, conversation_id, lock=True)
            if conversation.state == "interrompida" or conversation.opted_out_at:
                raise CommercialError("O cliente pediu para interromper esta conversa.")
            if conversation.channel == "whatsapp" and (not conversation.last_inbound_at or
                    as_utc(conversation.last_inbound_at) + timedelta(hours=24) <= utcnow()):
                raise CommercialError("A janela de resposta do WhatsApp encerrou.")
            if conversation.channel == "whatsapp" and not self.account_settings(tenant_id).whatsapp_ready:
                raise CommercialError("WhatsApp desta empresa ainda não foi configurado e habilitado.")
            conversation.state, conversation.pause_reason = "humano", "resposta_operador"
            self.cancel_pending(session, conversation.id)
            row = self.add_reply(session, conversation, text, "humano", engine="operador")
            session.commit()
            return support_message_data(row, private=True)

    def pause(self, tenant_id, conversation_id, paused):
        with self.sessions() as session:
            self.tenant(session, tenant_id, active=True)
            conversation = self.conversation(session, tenant_id, conversation_id, lock=True)
            if not paused and conversation.opted_out_at:
                raise CommercialError("Conversa interrompida pelo cliente; não retome automaticamente.")
            conversation.state, conversation.pause_reason = ("humano", "pausa_operador") if paused else ("bot", None)
            if paused:
                self.cancel_pending(session, conversation.id)
            else:
                conversation.auto_replies = 0
                for ticket in session.scalars(select(SupportHandoff).where(SupportHandoff.conversation_id == conversation.id,
                                                                         SupportHandoff.status == "aberto")):
                    ticket.status, ticket.closed_at = "resolvido", utcnow()
            session.commit()
            return support_conversation_data(conversation)

    def process_inbound(self):
        now = utcnow()
        with self.sessions() as session:
            session.execute(update(SupportMessage).where(SupportMessage.status == "em_analise",
                SupportMessage.processing_at < now - timedelta(minutes=3)).values(status="recebida", processing_at=None))
            identifier = session.scalar(select(SupportMessage.id).where(SupportMessage.direction == "entrada",
                SupportMessage.status == "recebida").order_by(SupportMessage.created_at, SupportMessage.id).limit(1))
            if not identifier:
                session.commit()
                return 0
            claimed = session.execute(update(SupportMessage).where(SupportMessage.id == identifier,
                SupportMessage.status == "recebida").values(status="em_analise", processing_at=now))
            session.commit()
            if claimed.rowcount != 1:
                return 0
        reason, decision, engine, confirmed = None, None, "regras_suporte", False
        with self.sessions() as session:
            inbound = session.get(SupportMessage, identifier)
            tenant = self.tenant(session, inbound.tenant_id, lock=True)
            conversation = self.conversation(session, tenant.id, inbound.conversation_id, lock=True)
            if abusive_message(inbound.text):
                inbound.status, inbound.engine = "ignorada", "filtro_abuso"
                session.commit()
                return 1
            if not tenant.active or conversation.state != "bot" or conversation.last_inbound_id != inbound.id:
                inbound.status = "processada"
                session.commit()
                return 1
            normalized = normalize_text(inbound.text)
            pending = conversation.pause_reason or ""
            if pending.startswith(CONFIRMATION_PREFIX):
                answer = confirmation_reply(inbound.text)
                if answer is True:
                    reason, confirmed = pending[len(CONFIRMATION_PREFIX):], True
                elif answer is False:
                    conversation.pause_reason = None
                    decision = SupportDecision(acao="responder", texto=DECLINE_HANDOFF, referencias=[])
                    engine = "confirmacao_recusada"
                elif normalized in {"talvez", "nao sei", "como assim"}:
                    decision = SupportDecision(acao="responder", texto="Quer que eu chame um responsável? Responda sim ou não.", referencias=[])
                    engine = "confirmacao_responsavel"
                else:
                    conversation.pause_reason = None
            if reason or decision:
                pass
            elif inbound.kind != "text":
                reason = "mensagem_de_midia"
            elif conversation.channel == "whatsapp" and not self.account_settings(tenant.id).whatsapp_ready:
                reason = "whatsapp_nao_configurado"
            elif explicit_human_request(inbound.text):
                reason = "precisa_responsavel"
            elif conversation.auto_replies >= 20:
                reason = "limite_conversa_automatica"
            elif conversation.channel == "whatsapp" and as_utc(inbound.occurred_at) + timedelta(hours=24) <= now:
                reason = "janela_resposta_encerrada"
            elif normalized in {"oi", "ola", "bom dia", "boa tarde", "boa noite"} and not (tenant.ai_enabled and self.settings.ai_configured):
                decision = SupportDecision(acao="responder", texto=tenant.welcome_text, referencias=[])
                engine = "boas_vindas"
            items = [] if reason or decision else session.scalars(select(SupportKnowledge).where(
                SupportKnowledge.tenant_id == tenant.id, SupportKnowledge.active.is_(True))
                .order_by(SupportKnowledge.created_at, SupportKnowledge.id).limit(100)).all()
            business_context = " ".join([tenant.name, *[row.title + " " + row.content for row in items]])
            if not reason and not decision and clearly_unrelated_message(inbound.text, business_context):
                inbound.status, inbound.engine = "ignorada", "filtro_assunto"
                session.commit()
                return 1
            selected = select_knowledge(items, inbound.text)
            if tenant.ai_enabled and self.settings.ai_configured:
                # Priorize a pergunta atual e complete com outros fatos da própria empresa.
                # A base é contexto factual; as respostas são elaboradas pelo modelo.
                selected = (selected + [item for item in items if item not in selected])[:5]
            if not reason and not decision and not selected:
                reason = "sem_resposta_na_base"
            use_ai = bool(selected and tenant.ai_enabled and self.settings.ai_configured)
            if use_ai and not self.reserve(session, tenant, "ai_calls", tenant.daily_ai_limit):
                reason, use_ai = "limite_ia_diario", False
            knowledge = [{"id": row.id, "titulo": row.title, "conteudo": row.content} for row in selected]
            history = [{"direcao": row.direction, "texto": row.text[:2000]} for row in reversed(session.scalars(
                select(SupportMessage).where(SupportMessage.conversation_id == conversation.id, SupportMessage.id != inbound.id)
                .where(SupportMessage.status != "ignorada")
                .order_by(SupportMessage.created_at.desc()).limit(8)).all())
                if row.direction != "entrada" or (not abusive_message(row.text) and
                    not clearly_unrelated_message(row.text, business_context))]
            tenant_id, conversation_id, current_text = tenant.id, conversation.id, inbound.text
            session.commit()
        if not reason and not decision:
            decision, engine = decide_support(self.settings, tenant, knowledge, current_text, history, use_ai, self.ai_transport)
            if decision.acao == "encaminhar":
                reason = "falha_ia" if engine == "falha_ia" else "avaliacao_responsavel"
        with self.sessions() as session:
            tenant = self.tenant(session, tenant_id, lock=True)
            conversation = self.conversation(session, tenant_id, conversation_id, lock=True)
            inbound = session.get(SupportMessage, identifier)
            existing = session.scalar(select(SupportMessage.id).where(SupportMessage.reply_to_id == identifier))
            if tenant.active and conversation.state == "bot" and conversation.last_inbound_id == identifier and not existing:
                for item in knowledge:
                    current = session.get(SupportKnowledge, item["id"])
                    if not current or not current.active or current.title != item["titulo"] or current.content != item["conteudo"]:
                        reason = "base_alterada_durante_resposta"
                        break
                if decision and decision.acao == "ignorar":
                    inbound.status, inbound.engine = "ignorada", "fora_de_contexto"
                    session.commit()
                    return 1
                if reason and (confirmed or reason in {"precisa_responsavel", "whatsapp_nao_configurado", "janela_resposta_encerrada"}):
                    source = inbound
                    if confirmed:
                        offer = session.scalar(select(SupportMessage).where(
                            SupportMessage.conversation_id == conversation.id, SupportMessage.direction == "saida",
                            SupportMessage.text == ASK_HANDOFF, SupportMessage.engine == "confirmacao_responsavel")
                            .order_by(SupportMessage.created_at.desc()).limit(1))
                        if offer and offer.reply_to_id:
                            original = session.get(SupportMessage, offer.reply_to_id)
                            if original and original.conversation_id == conversation.id:
                                source = original
                    self.handoff(session, conversation, source, reason)
                    if conversation.channel == "site" or (self.account_settings(tenant_id).whatsapp_ready and conversation.last_inbound_at and
                            as_utc(conversation.last_inbound_at) + timedelta(hours=24) > utcnow()):
                        self.add_reply(session, conversation, SUPPORT_HANDOFF, "sistema", inbound, engine)
                elif reason:
                    conversation.pause_reason = CONFIRMATION_PREFIX + reason
                    self.add_reply(session, conversation, ASK_HANDOFF, "sistema", inbound, "confirmacao_responsavel")
                else:
                    self.add_reply(session, conversation, decision.texto, "assistente", inbound, engine)
            inbound.status = "processada"
            session.commit()
        return 1

    def process_cycle(self):
        from .support_whatsapp import process_outbound
        return {"entradas_processadas": self.process_inbound(), "envios_processados": process_outbound(self)}
