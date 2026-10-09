"""Funil persistente, aplicação pública limitada e cadastro explícito do serviço vendido."""
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from atendeai.api import create_app
from atendeai.config import Settings
from atendeai.models import ApplicationRate, Lead, SalesApplication, SupportTenant

KEY = "funnel-test-admin-key-no-production-secret"
HEADERS = {"X-API-Key": KEY}


def application(**changes):
    return {"id_envio": str(uuid4()), "nome_empresa": "Restaurante Fictício", "cidade": "Campinas",
            "segmento": "restaurantes", "nome_contato": "Pessoa de Teste", "whatsapp": "+5519912345678",
            "canais": ["whatsapp", "site"], "volume": "ate_30", "objetivo": "Responder dúvidas sobre o cardápio e horários.",
            "autoriza_contato": True, **changes}


class FunnelTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Settings(environment="test", database_url="sqlite:///:memory:", admin_api_key=KEY))
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def submit(self, body=None):
        response = self.client.post("/publico/aplicacoes", json=body or application())
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["protocolo"]

    def test_public_form_and_browser_root_with_api_compatibility(self):
        for path in ("/aplicar", "/aplicar/formulario.js", "/marca.svg"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(KEY, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn("script-src 'self'", response.headers["content-security-policy"])
        html = self.client.get("/", headers={"Accept": "text/html"})
        self.assertIn("text/html", html.headers["content-type"])
        self.assertIn("Nelvo", html.text)
        self.assertIn("Accept", html.headers["vary"])
        self.assertEqual(self.client.get("/").json()["versao"], "0.6.0")

    def test_public_submission_stores_application_without_customer_or_outreach(self):
        body = application(); identifier = self.submit(body)
        response = self.client.post("/publico/aplicacoes", json=body)
        self.assertEqual(response.json()["protocolo"], identifier)
        self.assertNotIn("whatsapp", response.json())
        self.assertEqual(self.client.get("/v1/funil").status_code, 401)
        with self.app.state.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SalesApplication)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(SupportTenant)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(Lead)), 0)
        rows = self.client.get("/v1/funil", headers=HEADERS).json()["aplicacoes"]
        self.assertEqual(rows[0]["whatsapp"], body["whatsapp"])
        self.assertEqual(rows[0]["etapa"], "nova")
        self.assertEqual(self.client.get("/v1/comercial/mensagens", headers=HEADERS).json()["mensagens"], [])

    def test_invalid_fields_scope_and_contact_permission(self):
        for change in ({"autoriza_contato": False}, {"cidade": "Rio de Janeiro"}, {"segmento": "invalido"},
                       {"whatsapp": "12345"}, {"nome_empresa": "  "}, {"objetivo": " " * 30},
                       {"canais": []}, {"canais": ["email"]}, {"site_extra": "spam"}, {"extra": "field"}):
            response = self.client.post("/publico/aplicacoes", json=application(**change))
            self.assertEqual(response.status_code, 422, change)
        self.assertEqual(self.client.post("/publico/aplicacoes", json=application(), headers={"Origin": "https://other.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/publico/aplicacoes", content="x" * 17000, headers={"Content-Type": "application/json"}).status_code, 413)
        self.assertEqual(self.client.post("/publico/aplicacoes", content="text").status_code, 415)

    def test_submission_cap_and_idempotent_retry(self):
        body = application(); identifier = self.submit(body)
        for _ in range(4): self.submit()
        self.assertEqual(self.client.post("/publico/aplicacoes", json=application()).status_code, 429)
        self.assertEqual(self.client.post("/publico/aplicacoes", json=body).json()["protocolo"], identifier)

    def test_stages_filters_and_explicit_idempotent_conversion(self):
        identifier = self.submit()
        path = "/v1/funil/" + identifier
        body = {"nome": "Restaurante Cliente", "origens_permitidas": ["https://cliente.example.invalid"]}
        self.assertEqual(self.client.post(path + "/cliente", json=body).status_code, 401)
        self.assertEqual(self.client.post(path + "/cliente", json=body, headers=HEADERS).status_code, 409)
        self.client.patch(path, headers=HEADERS, json={"etapa": "proposta", "notas": "Próximo passo: apresentar integração."}).raise_for_status()
        self.assertEqual(self.client.get("/v1/funil?etapa=nova", headers=HEADERS).json()["total"], 0)
        self.assertEqual(self.client.get("/v1/funil?busca=Restaurante", headers=HEADERS).json()["total"], 1)
        self.client.patch(path, headers=HEADERS, json={"etapa": "ganha", "notas": "Contratação confirmada"}).raise_for_status()
        customer = self.client.post(path + "/cliente", json=body, headers=HEADERS).json()
        self.assertFalse(customer["ja_cadastrada"])
        self.assertIn("chave_site", customer["empresa"])
        self.assertFalse(customer["empresa"]["whatsapp_ativo"])
        repeated = self.client.post(path + "/cliente", json=body, headers=HEADERS).json()
        self.assertTrue(repeated["ja_cadastrada"])
        self.assertEqual(repeated["empresa"]["id"], customer["empresa"]["id"])
        self.assertNotIn("chave_site", repeated["empresa"])
        self.assertEqual(self.client.patch(path, headers=HEADERS, json={"etapa": "nova"}).status_code, 409)
        with self.app.state.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SupportTenant)), 1)

    def test_commercial_lead_requires_operator_review_and_separate_authorization(self):
        identifier = self.submit()
        path = "/v1/funil/" + identifier + "/empresa"
        self.assertEqual(self.client.post(path).status_code, 401)
        first = self.client.post(path, headers=HEADERS).json()["empresa_id"]
        self.assertEqual(self.client.post(path, headers=HEADERS).json()["empresa_id"], first)
        lead = self.client.get("/v1/empresas/" + first, headers=HEADERS).json()
        self.assertEqual(lead["revisao"], "pendente")
        self.assertEqual(lead["consentimento_whatsapp"], "desconhecido")
        self.assertFalse(lead["elegivel_para_etapa_comercial"])
        self.assertEqual(self.client.get("/v1/comercial/fila", headers=HEADERS).json()["quantidade"], 0)

    def test_summary_includes_actual_records_without_exposing_data_publicly(self):
        self.submit()
        self.assertEqual(self.client.get("/v1/funil/resumo").status_code, 401)
        summary = self.client.get("/v1/funil/resumo", headers=HEADERS).json()
        self.assertEqual(summary["clientes"], 0)
        self.assertEqual(summary["etapas"][0]["quantidade"], 1)
        self.assertEqual(self.client.get("/publico/aplicacoes").status_code, 405)


if __name__ == "__main__": unittest.main()
