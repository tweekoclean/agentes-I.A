"""Acesso do operador e limites entre a interface pública e os dados privados."""
import unittest

from fastapi.testclient import TestClient

from atendeai.api import create_app
from atendeai.config import Settings
from atendeai.models import SupportConversation
from atendeai.support import support_conversation_data

KEY = "panel-test-key-only-for-local-tests"


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Settings(environment="test", database_url="sqlite:///:memory:", admin_api_key=KEY))
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def test_public_interface_has_no_administrative_secret_and_blocks_embedding(self):
        for path in ("/painel", "/painel/painel.css", "/painel/painel.js"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(KEY, response.text)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
            self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(self.client.get("/").json()["painel"], "/painel")

    def test_panel_does_not_grant_access_to_private_data(self):
        self.client.get("/painel")
        for headers in ({}, {"X-API-Key": "incorrect-key"}):
            response = self.client.get("/v1/atendimento/empresas", headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        response = self.client.get("/v1/atendimento/empresas", headers={"X-API-Key": KEY})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_whatsapp_recipient_is_available_only_to_operator(self):
        tenant = self.client.post("/v1/atendimento/empresas", headers={"X-API-Key": KEY}, json={"nome": "Empresa fictícia"}).json()
        with self.app.state.sessions() as session:
            conversation = SupportConversation(tenant_id=tenant["id"], channel="whatsapp", recipient="+5519912345678")
            session.add(conversation)
            session.commit()
            conversation_id = conversation.id
            self.assertNotIn("contato", support_conversation_data(conversation))
        path = f"/v1/atendimento/empresas/{tenant['id']}/conversas"
        listing = self.client.get(path, headers={"X-API-Key": KEY}).json()
        self.assertEqual(listing["conversas"][0]["contato"], "+5519912345678")
        detail = self.client.get(path + "/" + conversation_id, headers={"X-API-Key": KEY}).json()
        self.assertEqual(detail["conversa"]["contato"], "+5519912345678")
        self.assertEqual(self.client.get(path).status_code, 401)


if __name__ == "__main__":
    unittest.main()
