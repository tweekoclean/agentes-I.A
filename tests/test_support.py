"""Suporte de empresas fictícias; HTTP simulado, nenhum envio real."""
from dataclasses import replace
from datetime import timedelta
import hashlib
import hmac
import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
from sqlalchemy import func, select

from atendeai.api import create_app
from atendeai.config import Settings
from atendeai.models import SupportConversation, SupportMessage, SupportQuota, SupportTenant, utcnow
from atendeai.support import SUPPORT_HANDOFF
from atendeai.support_whatsapp import process_outbound
from atendeai.support_policy import ASK_HANDOFF, DECLINE_HANDOFF

KEY = "support-test-administrative-key-not-secret"
ADMIN = {"X-API-Key": KEY}
ORIGIN = "https://customer.example.invalid"
PHONE = "+5519912345678"


class SupportTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(environment="test", database_url="sqlite:///:memory:", admin_api_key=KEY)
        self.calls, self.ai_calls = [], []
        self.meta_handler = lambda request: httpx.Response(200, json={"messages": [{"id": f"wamid.support.{len(self.calls)}"}]})
        self.ai_handler = lambda request: httpx.Response(503)
        def meta(request):
            self.calls.append(request)
            return self.meta_handler(request)
        def ai(request):
            self.ai_calls.append(request)
            return self.ai_handler(request)
        self.app = create_app(self.settings, ai_transport=httpx.MockTransport(ai), whatsapp_transport=httpx.MockTransport(meta))
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()
        self.service, self.sessions = self.app.state.support, self.app.state.sessions

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def post(self, path, body=None, expected=200):
        r = self.client.post(path, headers=ADMIN, json=body)
        self.assertEqual(r.status_code, expected, r.text)
        return r.json()

    def tenant(self, name="Loja Fictícia A", **changes):
        return self.post("/v1/atendimento/empresas", {"nome": name, "origens_permitidas": [ORIGIN], **changes})

    def knowledge(self, tenant, text="Funcionamos de segunda a sexta, das 9h às 18h."):
        return self.post(f"/v1/atendimento/empresas/{tenant['id']}/base", {"titulo": "Horário de atendimento", "conteudo": text})

    def chat(self, tenant, expected=200, origin=ORIGIN, key=None):
        r = self.client.post(f"/v1/atendimento/site/{tenant['id']}/conversas",
                            headers={"Origin": origin, "X-Site-Key": key or tenant["chave_site"]})
        self.assertEqual(r.status_code, expected, r.text)
        return r.json()

    def path(self, tenant, chat):
        return f"/v1/atendimento/site/{tenant['id']}/conversas/{chat['conversa']['id']}/mensagens"

    def site_headers(self, chat):
        return {"Origin": ORIGIN, "Authorization": "Bearer " + chat["token_conversa"]}

    def send(self, tenant, chat, text="Qual o horário de atendimento?", client_id="message-1", expected=200):
        r = self.client.post(self.path(tenant, chat), headers=self.site_headers(chat), json={"texto": text, "id_cliente": client_id})
        self.assertEqual(r.status_code, expected, r.text)
        return r.json()

    def history(self, tenant, chat):
        r = self.client.get(self.path(tenant, chat), headers=self.site_headers(chat))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        return r.json()

    def tickets(self, tenant):
        return self.client.get(f"/v1/atendimento/empresas/{tenant['id']}/chamados", headers=ADMIN).json()["chamados"]

    def test_same_origin_history_accepts_browser_referer_without_weakening_token_or_origin(self):
        tenant = self.tenant()
        chat = self.chat(tenant)
        headers = {"Authorization": "Bearer " + chat["token_conversa"], "Referer": ORIGIN + "/teste-atendimento?empresa=public"}
        response = self.client.get(self.path(tenant, chat), headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("contato", response.json()["conversa"])
        self.assertEqual(self.client.get(self.path(tenant, chat), headers={**headers, "Origin": "https://other.example.invalid"}).status_code, 403)
        self.assertEqual(self.client.get(self.path(tenant, chat), headers={**headers, "Authorization": "Bearer incorrect"}).status_code, 401)
        self.assertEqual(self.client.get(self.path(tenant, chat), headers={"Authorization": headers["Authorization"]}).status_code, 403)
        self.assertEqual(self.client.get(self.path(tenant, chat), headers={**headers, "Referer": "https://[invalid"}).status_code, 403)

    def configure_whatsapp(self, tenant):
        account = {"enabled": True, "token": "fake-support-token", "phone_number_id": "987654321",
                   "app_secret": "fake-support-secret", "verify_token": "fake-support-verify", "api_version": "v24.0"}
        self.service.settings = replace(self.service.settings, support_whatsapp_accounts={tenant["id"]: account})
        return account

    def whatsapp_event(self, text="Qual o horário de atendimento?", remote_id="wamid.input.support", when=None, phone_id="987654321"):
        return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": phone_id}, "messages": [{"type": "text", "from": PHONE.lstrip("+"),
                "id": remote_id, "timestamp": str(int((when or utcnow()).timestamp())), "text": {"body": text}}]}}]}]}

    def webhook(self, tenant, account, payload, expected=200, secret=None):
        body = json.dumps(payload, ensure_ascii=False).encode()
        signature = "sha256=" + hmac.new((secret or account["app_secret"]).encode(), body, hashlib.sha256).hexdigest()
        r = self.client.post(f"/webhooks/atendimento/whatsapp/{tenant['id']}", content=body, headers={"X-Hub-Signature-256": signature})
        self.assertEqual(r.status_code, expected, r.text)
        return r

    def ai_result(self, item_id, text="O atendimento ocorre das 9h às 18h."):
        return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps({"acao": "responder", "texto": text, "referencias": [item_id]})}})

    def test_admin_authentication_origin_validation_and_no_credential_leak(self):
        self.assertEqual(self.client.get("/v1/atendimento/empresas").status_code, 401)
        self.assertEqual(self.client.post("/v1/atendimento/empresas", json={"nome": "Teste"}).status_code, 401)
        for origin in ["http://customer.example.invalid", "https://customer.example.invalid/path", "https://user:password@example.invalid"]:
            self.post("/v1/atendimento/empresas", {"nome": "Teste", "origens_permitidas": [origin]}, expected=422)
        tenant = self.tenant()
        listing = self.client.get("/v1/atendimento/empresas", headers=ADMIN)
        self.assertNotIn(tenant["chave_site"], listing.text)
        self.assertNotIn("site_key_hash", listing.text)
        with self.sessions() as session:
            self.assertNotEqual(session.get(SupportTenant, tenant["id"]).site_key_hash, tenant["chave_site"])
        self.chat(tenant, key="wrong-key", expected=401)
        self.chat(tenant, origin="https://other.example.invalid", expected=403)

    def test_cors_and_widget_are_available_without_admin_key(self):
        r = self.client.options("/v1/atendimento/site/example/conversas", headers={"Origin": ORIGIN,
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "X-Site-Key,Content-Type"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("access-control-allow-origin", r.headers)
        widget = self.client.get("/widget/atendeai.js")
        self.assertEqual(widget.status_code, 200)
        self.assertIn("application/javascript", widget.headers["content-type"])
        self.assertEqual(self.client.get("/teste-atendimento").status_code, 200)

    def test_site_key_rotation_revokes_new_sessions_using_old_key(self):
        tenant = self.tenant()
        chat = self.chat(tenant)
        key = self.post(f"/v1/atendimento/empresas/{tenant['id']}/chave-site")["chave_site"]
        self.chat(tenant, expected=401)
        self.chat({**tenant, "chave_site": key})
        self.assertEqual(self.history(tenant, chat)["conversa"]["id"], chat["conversa"]["id"])

    def test_site_session_tokens_and_tenant_ids_prevent_cross_customer_access(self):
        tenant, other = self.tenant(), self.tenant("Loja Fictícia B")
        first, second = self.chat(tenant), self.chat(tenant)
        self.send(tenant, first, "Mensagem privada do visitante A")
        self.assertEqual(self.client.get(self.path(tenant, first), headers=self.site_headers(second)).status_code, 401)
        self.assertEqual(self.client.get(self.path(other, first), headers=self.site_headers(first)).status_code, 404)
        self.assertEqual(self.client.get(self.path(tenant, first), headers={"Origin": ORIGIN}).status_code, 401)
        self.assertEqual(self.client.get(self.path(tenant, first), headers={**self.site_headers(first), "Origin": "https://other.example.invalid"}).status_code, 403)
        self.assertNotIn("Mensagem privada", json.dumps(self.history(tenant, second)))
        with self.sessions() as session:
            self.assertNotEqual(session.get(SupportConversation, first["conversa"]["id"]).token_hash, first["token_conversa"])

    def test_knowledge_responses_are_isolated_between_companies(self):
        first, second = self.tenant(), self.tenant("Loja Fictícia B")
        self.knowledge(first, "A loja A abre às 9h.")
        second_item = self.knowledge(second, "A loja B abre às 14h.")
        chats = [self.chat(first), self.chat(second)]
        for tenant, chat in zip([first, second], chats):
            self.send(tenant, chat)
            self.post("/v1/atendimento/processar")
        self.assertEqual(self.history(first, chats[0])["mensagens"][-1]["texto"], "A loja A abre às 9h.")
        self.assertEqual(self.history(second, chats[1])["mensagens"][-1]["texto"], "A loja B abre às 14h.")
        r = self.client.put(f"/v1/atendimento/empresas/{first['id']}/base/{second_item['id']}", headers=ADMIN,
                           json={"titulo": "Horário", "conteudo": "Conteúdo indevido"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.ai_calls, [])

    def test_message_idempotency_and_conflicting_client_ids(self):
        tenant = self.tenant()
        self.knowledge(tenant)
        chat = self.chat(tenant)
        first = self.send(tenant, chat)
        self.assertEqual(self.send(tenant, chat)["id"], first["id"])
        self.send(tenant, chat, text="Outro texto", expected=409)
        self.post("/v1/atendimento/processar")
        self.post("/v1/atendimento/processar")
        self.assertEqual(len(self.history(tenant, chat)["mensagens"]), 3)

    def test_unknown_question_requests_confirmation_before_opening_ticket(self):
        tenant = self.tenant()
        self.knowledge(tenant)
        chat = self.chat(tenant)
        self.send(tenant, chat, "Onde está meu pedido 123?")
        self.post("/v1/atendimento/processar")
        history = self.history(tenant, chat)
        self.assertEqual(history["mensagens"][-1]["texto"], ASK_HANDOFF)
        self.assertEqual(history["conversa"]["estado"], "bot")
        self.assertTrue(history["conversa"]["aguardando_confirmacao"])
        self.assertEqual(self.tickets(tenant), [])
        self.send(tenant, chat, "SS!", client_id="confirm")
        self.post("/v1/atendimento/processar")
        history = self.history(tenant, chat)
        self.assertEqual(history["mensagens"][-1]["texto"], SUPPORT_HANDOFF)
        self.assertEqual(history["conversa"]["estado"], "humano")
        self.assertEqual(len(self.tickets(tenant)), 1)
        self.assertIn("pedido 123", self.tickets(tenant)[0]["resumo"])
        self.send(tenant, chat, client_id="second")
        self.post("/v1/atendimento/processar")
        self.assertEqual(len(self.tickets(tenant)), 1)
        self.assertEqual(len(self.history(tenant, chat)["mensagens"]), 6)

    def test_human_response_reaches_same_visitor_and_resume_resolves_ticket(self):
        tenant = self.tenant()
        chat = self.chat(tenant)
        self.send(tenant, chat, "Quero falar com um atendente")
        self.post("/v1/atendimento/processar")
        root = f"/v1/atendimento/empresas/{tenant['id']}/conversas/{chat['conversa']['id']}"
        self.post(root + "/responder", {"texto": "Olá, aqui é o responsável. Vou verificar seu pedido."})
        self.assertEqual(self.history(tenant, chat)["mensagens"][-1]["autor"], "humano")
        self.assertEqual(self.history(tenant, chat)["conversa"]["estado"], "humano")
        self.post(root + "/pausa", {"pausado": False})
        self.assertEqual(self.tickets(tenant), [])
        self.assertEqual(self.history(tenant, chat)["conversa"]["estado"], "bot")

    def test_deactivated_company_blocks_visitor_reads_new_chats_and_queued_bot(self):
        tenant = self.tenant()
        self.knowledge(tenant)
        chat = self.chat(tenant)
        self.send(tenant, chat)
        r = self.client.patch(f"/v1/atendimento/empresas/{tenant['id']}", headers=ADMIN, json={"ativa": False})
        self.assertEqual(r.status_code, 200)
        self.chat(tenant, expected=404)
        self.assertEqual(self.client.get(self.path(tenant, chat), headers=self.site_headers(chat)).status_code, 404)
        self.post("/v1/atendimento/processar")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SupportMessage).where(
                SupportMessage.tenant_id == tenant["id"], SupportMessage.author == "assistente")), 0)

    def test_daily_public_session_limit_is_persisted(self):
        tenant = self.tenant(limite_conversas_dia=1)
        self.chat(tenant)
        self.chat(tenant, expected=429)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(SupportQuota)).conversations_opened, 1)

    def test_ai_context_uses_only_own_company_and_invalid_references_handoff(self):
        tenant, other = self.tenant(ia_habilitada=True), self.tenant("Outra empresa")
        self.knowledge(tenant)
        other_item = self.knowledge(other, "Outra empresa: informação exclusiva ABC987.")
        self.service.settings = replace(self.service.settings, ai_provider="ollama")
        chat = self.chat(tenant)
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(request.url.host, "127.0.0.1")
            self.assertFalse(body["stream"])
            self.assertFalse(body["format"]["additionalProperties"])
            self.assertNotIn("ABC987", body["messages"][1]["content"])
            self.assertNotIn(chat["token_conversa"], body["messages"][1]["content"])
            return self.ai_result("2", "Informação de outra empresa")
        self.ai_handler = handler
        self.send(tenant, chat)
        self.post("/v1/atendimento/processar")
        self.assertEqual(len(self.ai_calls), 1)
        self.assertEqual(self.history(tenant, chat)["mensagens"][-1]["texto"], ASK_HANDOFF)
        self.assertEqual(self.tickets(tenant), [])
        self.send(tenant, chat, "sim", client_id="confirm")
        self.post("/v1/atendimento/processar")
        self.assertEqual(self.tickets(tenant)[0]["motivo"], "falha_ia")

    def test_valid_ai_answer_and_daily_ai_budget(self):
        tenant = self.tenant(ia_habilitada=True, limite_ia_dia=1)
        item = self.knowledge(tenant)
        self.service.settings = replace(self.service.settings, ai_provider="ollama")
        self.ai_handler = lambda request: self.ai_result("1")
        first = self.chat(tenant)
        self.send(tenant, first)
        self.post("/v1/atendimento/processar")
        self.assertEqual(self.history(tenant, first)["mensagens"][-1]["modo"], "ia")
        second = self.chat(tenant)
        self.send(tenant, second)
        self.post("/v1/atendimento/processar")
        self.assertEqual(len(self.ai_calls), 1)
        self.assertEqual(self.tickets(tenant), [])
        self.send(tenant, second, "Sim", client_id="confirm")
        self.post("/v1/atendimento/processar")
        self.assertEqual(self.tickets(tenant)[0]["motivo"], "limite_ia_diario")

    def test_ai_can_use_small_base_for_a_question_with_different_wording(self):
        tenant = self.tenant(ia_habilitada=True)
        item = self.knowledge(tenant)
        self.service.settings = replace(self.service.settings, ai_provider="ollama")
        self.ai_handler = lambda request: self.ai_result("1", "Abrimos às 9h.")
        chat = self.chat(tenant)
        self.send(tenant, chat, "Até que horas vocês ficam abertos?")
        self.post("/v1/atendimento/processar")
        self.assertEqual(len(self.ai_calls), 1)
        self.assertEqual(self.history(tenant, chat)["mensagens"][-1]["texto"], "Abrimos às 9h.")

    def test_knowledge_changed_during_ai_analysis_is_not_sent_as_current_policy(self):
        tenant = self.tenant(ia_habilitada=True)
        item = self.knowledge(tenant)
        self.service.settings = replace(self.service.settings, ai_provider="ollama")
        chat = self.chat(tenant)
        def handler(request):
            changed = self.client.put(f"/v1/atendimento/empresas/{tenant['id']}/base/{item['id']}", headers=ADMIN,
                                      json={"titulo": item["titulo"], "conteudo": "Novo horário: das 14h às 20h."})
            self.assertEqual(changed.status_code, 200)
            return self.ai_result("1", "Horário antigo das 9h às 18h.")
        self.ai_handler = handler
        self.send(tenant, chat)
        self.post("/v1/atendimento/processar")
        self.assertEqual(self.history(tenant, chat)["mensagens"][-1]["texto"], ASK_HANDOFF)
        self.send(tenant, chat, "ss", client_id="confirm")
        self.post("/v1/atendimento/processar")
        self.assertEqual(self.tickets(tenant)[0]["motivo"], "base_alterada_durante_resposta")

    def test_confirmation_accepts_case_and_short_variations_without_ai_call(self):
        for answer in ["sim", "Sim", "SIM", "ss", "Ss", "SS!", "s", "pode chamar"]:
            with self.subTest(answer=answer):
                tenant = self.tenant()
                chat = self.chat(tenant)
                self.send(tenant, chat, "Quanto custa o serviço?")
                self.service.process_cycle()
                self.assertEqual(self.tickets(tenant), [])
                self.send(tenant, chat, answer, client_id="confirm")
                self.service.process_cycle()
                self.assertEqual(self.history(tenant, chat)["conversa"]["estado"], "humano")
                self.assertEqual(len(self.tickets(tenant)), 1)
        self.assertEqual(self.ai_calls, [])

    def test_declining_handoff_keeps_bot_active_and_can_answer_next_question(self):
        tenant = self.tenant()
        self.knowledge(tenant)
        chat = self.chat(tenant)
        self.send(tenant, chat, "Qual preço?")
        self.service.process_cycle()
        self.send(tenant, chat, "nn", client_id="decline")
        self.service.process_cycle()
        history = self.history(tenant, chat)
        self.assertFalse(history["conversa"]["aguardando_confirmacao"])
        self.assertEqual(history["mensagens"][-1]["texto"], DECLINE_HANDOFF)
        self.assertEqual(self.tickets(tenant), [])
        self.send(tenant, chat, "Qual horário de atendimento?", client_id="next")
        self.service.process_cycle()
        self.assertEqual(self.history(tenant, chat)["mensagens"][-1]["modo"], "base_sem_ia")

    def test_abuse_is_silent_and_excluded_from_next_ai_context(self):
        tenant = self.tenant(ia_habilitada=True)
        self.knowledge(tenant)
        self.service.settings = replace(self.service.settings, ai_provider="ollama")
        chat = self.chat(tenant)
        for index, message in enumerate(["chupa meu pênis", "posso matar você", "vou te matar", "vai se foder"]):
            self.send(tenant, chat, message, client_id=f"abuse-{index}")
        for _ in range(4):
            self.service.process_cycle()
        history = self.history(tenant, chat)
        self.assertEqual(sum(m["direcao"] == "saida" for m in history["mensagens"]), 1)
        self.assertTrue(all(m["status"] == "ignorada" for m in history["mensagens"] if m["direcao"] == "entrada"))
        self.assertEqual(self.ai_calls, [])
        self.assertEqual(self.tickets(tenant), [])
        def handler(request):
            self.assertNotIn("matar", request.content.decode())
            self.assertNotIn("penis", request.content.decode())
            self.assertNotIn("pênis", request.content.decode())
            return self.ai_result("1")
        self.ai_handler = handler
        self.send(tenant, chat, "Qual horário?", client_id="normal")
        self.service.process_cycle()
        self.assertEqual(self.history(tenant, chat)["mensagens"][-1]["modo"], "ia")

    def test_off_topic_ai_decision_sends_nothing_and_opens_no_ticket(self):
        tenant = self.tenant(ia_habilitada=True)
        self.knowledge(tenant)
        self.service.settings = replace(self.service.settings, ai_provider="ollama")
        self.ai_handler = lambda request: httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps({"acao": "ignorar", "texto": "Ignorando.", "referencias": []})}})
        chat = self.chat(tenant)
        self.send(tenant, chat, "Qual a capital do Japão?")
        self.service.process_cycle()
        history = self.history(tenant, chat)
        self.assertEqual(len(history["mensagens"]), 2)
        self.assertEqual(history["mensagens"][-1]["status"], "ignorada")
        self.assertEqual(self.tickets(tenant), [])

    def test_yes_without_pending_confirmation_does_not_open_human_ticket(self):
        tenant = self.tenant()
        chat = self.chat(tenant)
        self.send(tenant, chat, "ss")
        self.service.process_cycle()
        self.assertEqual(self.history(tenant, chat)["conversa"]["estado"], "bot")
        self.assertEqual(self.tickets(tenant), [])

    def test_whatsapp_confirmation_uses_same_flow_with_simulated_sends(self):
        tenant = self.tenant()
        account = self.configure_whatsapp(tenant)
        self.webhook(tenant, account, self.whatsapp_event("Quanto custa o serviço?", remote_id="wamid.ask"))
        self.service.process_cycle()
        self.assertEqual(self.tickets(tenant), [])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(json.loads(self.calls[0].content)["text"]["body"], ASK_HANDOFF)
        self.webhook(tenant, account, self.whatsapp_event("Ss", remote_id="wamid.confirm"))
        self.service.process_cycle()
        self.assertEqual(len(self.tickets(tenant)), 1)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(json.loads(self.calls[1].content)["text"]["body"], SUPPORT_HANDOFF)

    def test_confirmation_survives_a_new_service_instance(self):
        from atendeai.support import SupportService
        tenant = self.tenant()
        chat = self.chat(tenant)
        self.send(tenant, chat, "Qual preço?")
        self.service.process_cycle()
        self.send(tenant, chat, "Sim", client_id="confirm-after-restart")
        fresh = SupportService(self.sessions, self.settings)
        fresh.process_cycle()
        self.assertEqual(self.history(tenant, chat)["conversa"]["estado"], "humano")
        self.assertEqual(len(self.tickets(tenant)), 1)

    def test_food_order_and_handoff_policy_question_are_not_blocked_as_abuse_or_human_request(self):
        tenant = self.tenant(ia_habilitada=True)
        self.knowledge(tenant, "O restaurante serve picanha e oferece entrega. Atendentes assumem quando solicitado.")
        self.service.settings = replace(self.service.settings, ai_provider="ollama")
        self.ai_handler = lambda request: self.ai_result("1", "Qual quantidade você deseja?")
        chat = self.chat(tenant)
        for index, text in enumerate(["Quero matar minha fome e pedir picanha", "Quando vocês chamam um responsável?"]):
            self.send(tenant, chat, text, client_id=f"business-{index}")
            self.service.process_cycle()
            self.assertEqual(self.history(tenant, chat)["mensagens"][-1]["modo"], "ia")
        self.assertEqual(self.tickets(tenant), [])


    def test_human_takeover_during_ai_analysis_discards_pending_bot_response(self):
        tenant = self.tenant(ia_habilitada=True)
        item = self.knowledge(tenant)
        self.service.settings = replace(self.service.settings, ai_provider="ollama")
        chat = self.chat(tenant)
        def handler(request):
            self.service.human_reply(tenant["id"], chat["conversa"]["id"], "Vou assumir o atendimento.")
            return self.ai_result("1", "Resposta da IA")
        self.ai_handler = handler
        self.send(tenant, chat)
        self.post("/v1/atendimento/processar")
        self.assertEqual(self.history(tenant, chat)["mensagens"][-1]["texto"], "Vou assumir o atendimento.")
        self.assertFalse(any(row["texto"] == "Resposta da IA" for row in self.history(tenant, chat)["mensagens"]))

    def test_whatsapp_signature_verification_and_wrong_number_are_isolated(self):
        tenant = self.tenant()
        account = self.configure_whatsapp(tenant)
        params = {"hub.mode": "subscribe", "hub.verify_token": account["verify_token"], "hub.challenge": "1234"}
        r = self.client.get(f"/webhooks/atendimento/whatsapp/{tenant['id']}", params=params)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, "1234")
        self.webhook(tenant, account, self.whatsapp_event(), secret="wrong", expected=401)
        self.webhook(tenant, account, self.whatsapp_event(phone_id="123456789"))
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SupportMessage)), 0)

    def test_whatsapp_reply_needs_inbound_window_and_is_not_a_marketing_opening(self):
        tenant = self.tenant()
        self.knowledge(tenant)
        account = self.configure_whatsapp(tenant)
        event = self.whatsapp_event()
        self.webhook(tenant, account, event)
        self.webhook(tenant, account, event)
        self.post("/v1/atendimento/processar")
        self.post("/v1/atendimento/processar")
        self.assertEqual(len(self.calls), 1)
        payload = json.loads(self.calls[0].content)
        self.assertEqual(payload["type"], "text")
        self.assertEqual(payload["to"], PHONE.lstrip("+"))
        self.assertIn("987654321/messages", str(self.calls[0].url))
        with self.sessions() as session:
            output = session.scalar(select(SupportMessage).where(SupportMessage.direction == "saida"))
            self.assertEqual(output.status, "aceita")
            self.assertIsNone(output.delivery_status)

    def test_whatsapp_opt_out_cancels_queued_reply_and_blocks_operator(self):
        tenant = self.tenant()
        self.knowledge(tenant)
        account = self.configure_whatsapp(tenant)
        self.webhook(tenant, account, self.whatsapp_event())
        self.service.process_inbound()
        self.webhook(tenant, account, self.whatsapp_event("SAIR", remote_id="wamid.optout"))
        process_outbound(self.service)
        self.assertEqual(self.calls, [])
        with self.sessions() as session:
            conversation = session.scalar(select(SupportConversation))
            self.assertEqual(conversation.state, "interrompida")
            output = session.scalar(select(SupportMessage).where(SupportMessage.direction == "saida"))
            self.assertEqual(output.status, "cancelada")
            identifier = conversation.id
        self.post(f"/v1/atendimento/empresas/{tenant['id']}/conversas/{identifier}/responder", {"texto": "Outro contato"}, expected=409)

    def test_whatsapp_customer_can_explicitly_restart_after_stopping(self):
        tenant = self.tenant()
        account = self.configure_whatsapp(tenant)
        stop_time = utcnow() - timedelta(minutes=2)
        self.webhook(tenant, account, self.whatsapp_event("SAIR", when=stop_time))
        self.webhook(tenant, account, self.whatsapp_event("Oi", remote_id="wamid.hello", when=stop_time + timedelta(seconds=30)))
        self.post("/v1/atendimento/processar")
        self.assertEqual(self.calls, [])
        self.webhook(tenant, account, self.whatsapp_event("quero atendimento novamente", remote_id="wamid.restart"))
        self.post("/v1/atendimento/processar")
        self.assertEqual(len(self.calls), 1)
        self.webhook(tenant, account, self.whatsapp_event("SAIR", remote_id="wamid.delayed", when=stop_time + timedelta(seconds=10)))
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(SupportConversation)).state, "bot")

    def test_whatsapp_expired_window_and_network_uncertainty_never_resend(self):
        tenant = self.tenant()
        self.knowledge(tenant)
        account = self.configure_whatsapp(tenant)
        self.webhook(tenant, account, self.whatsapp_event(when=utcnow() - timedelta(hours=25)))
        self.post("/v1/atendimento/processar")
        self.assertEqual(self.calls, [])
        with self.sessions() as session:
            identifier = session.scalar(select(SupportConversation)).id
        self.post(f"/v1/atendimento/empresas/{tenant['id']}/conversas/{identifier}/pausa", {"pausado": False})
        self.webhook(tenant, account, self.whatsapp_event(remote_id="wamid.new"))
        def timeout(request):
            raise httpx.ReadTimeout("fake-support-token", request=request)
        self.meta_handler = timeout
        self.post("/v1/atendimento/processar")
        self.post("/v1/atendimento/processar")
        self.assertEqual(len(self.calls), 1)
        with self.sessions() as session:
            output = session.scalar(select(SupportMessage).where(SupportMessage.direction == "saida"))
            self.assertEqual(output.status, "envio_incerto")
            self.assertNotIn("fake-support-token", output.error)

    def test_demo_can_answer_a_followup_after_local_ai_is_enabled(self):
        from atendeai.support import DEMO_TENANT_ID, DEMO_SITE_KEY, DEMO_ORIGIN
        self.service.ensure_demo()
        self.service.settings = replace(self.service.settings, ai_provider="ollama")
        updated = self.client.patch(f"/v1/atendimento/empresas/{DEMO_TENANT_ID}", headers=ADMIN,
                                    json={"ia_habilitada": True})
        self.assertEqual(updated.status_code, 200)
        self.ai_handler = lambda request: self.ai_result("1")
        self.service.ensure_demo()
        chat = self.chat({"id": DEMO_TENANT_ID, "chave_site": DEMO_SITE_KEY}, origin=DEMO_ORIGIN)
        path = self.path({"id": DEMO_TENANT_ID}, chat)
        headers = {"Origin": DEMO_ORIGIN, "Authorization": "Bearer " + chat["token_conversa"]}
        for index, question in enumerate(["Como vocês ajudam com meu site?", "E o WhatsApp?"]):
            sent = self.client.post(path, headers=headers, json={"texto": question, "id_cliente": f"local-demo-{index}"})
            self.assertEqual(sent.status_code, 200)
            self.service.process_cycle()
            history = self.client.get(path, headers=headers).json()
            self.assertEqual(history["conversa"]["estado"], "bot")
            self.assertEqual(history["mensagens"][-1]["modo"], "ia")
        self.assertEqual(len(self.ai_calls), 2)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(SupportQuota)).ai_calls, 2)
            self.assertTrue(session.get(SupportTenant, DEMO_TENANT_ID).ai_enabled)
        self.assertEqual(self.calls, [])

    def test_demo_is_idempotent_and_never_activates_paid_ai(self):
        from atendeai.support import DEMO_TENANT_ID, DEMO_SITE_KEY, DEMO_ORIGIN
        self.service.ensure_demo()
        self.service.ensure_demo()
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SupportTenant)), 1)
            tenant = session.get(SupportTenant, DEMO_TENANT_ID)
            self.assertFalse(tenant.ai_enabled)
            self.assertEqual(tenant.name, "AtendeAI — Demonstração")
        response = self.client.get("/demonstracao", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        chat = self.chat({"id": DEMO_TENANT_ID, "chave_site": DEMO_SITE_KEY}, origin=DEMO_ORIGIN)
        path = self.path({"id": DEMO_TENANT_ID}, chat)
        headers = {"Origin": DEMO_ORIGIN, "Authorization": "Bearer " + chat["token_conversa"]}
        sent = self.client.post(path, headers=headers, json={"texto": "quais serviços vocês oferecem?", "id_cliente": "demo-1"})
        self.assertEqual(sent.status_code, 200)
        self.service.process_cycle()
        history = self.client.get(path, headers=headers).json()
        self.assertEqual(history["mensagens"][-1]["modo"], "base_sem_ia")
        self.assertEqual(self.ai_calls, [])
        self.assertEqual(self.calls, [])


class SupportConfigurationTests(unittest.TestCase):
    def test_environment_accounts_are_private_and_duplicates_rejected(self):
        identifier = "12345678-1234-1234-1234-123456789abc"
        account = {"enabled": True, "token": "private-test-token", "phone_number_id": "987654321",
                   "app_secret": "private-test-app-secret", "verify_token": "private-test-verify-token"}
        with patch.dict(os.environ, {"SUPPORT_WHATSAPP_ACCOUNTS_JSON": json.dumps({identifier: account})}, clear=True):
            settings = Settings.from_env()
        self.assertNotIn(account["token"], repr(settings))
        self.assertNotIn(account["app_secret"], repr(settings))
        settings.validated()
        with self.assertRaises(ValueError):
            replace(settings, whatsapp_phone_number_id="987654321").validated()
        with self.assertRaises(ValueError):
            replace(settings, support_whatsapp_accounts={identifier: {**account, "enabled": "true"}}).validated()


if __name__ == "__main__":
    unittest.main()
