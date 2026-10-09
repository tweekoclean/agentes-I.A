"""Funil persistente, aplicação pública limitada e cadastro explícito do serviço vendido."""
import unittest
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

from atendeai.api import create_app
from atendeai.config import Settings
from atendeai.models import ApplicationProject, ApplicationRate, Base, Lead, SalesApplication, SupportTenant

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
        for path in ("/aplicar", "/aplicar/formulario.js", "/marca.svg", "/home/home.css", "/home/home.js"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(KEY, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn("script-src 'self'", response.headers["content-security-policy"])
        html = self.client.get("/", headers={"Accept": "text/html"})
        self.assertIn("text/html", html.headers["content-type"])
        self.assertIn("Nelvo", html.text)
        self.assertIn('class="home-page"', html.text)
        self.assertNotIn('id="public-application-form"', html.text)
        self.assertIn('href="/aplicar"', html.text)
        self.assertIn('src="/marca.png"', html.text)
        self.assertIn('id="public-application-form"', self.client.get("/aplicar").text)
        self.assertNotIn("SÃO PAULO", html.text + self.client.get("/aplicar").text)
        logo = self.client.get("/marca.png")
        self.assertEqual(logo.headers["content-type"], "image/png")
        self.assertTrue(logo.content.startswith(b"\x89PNG"))
        self.assertIn("Accept", html.headers["vary"])
        self.assertEqual(self.client.get("/").json()["versao"], "0.7.0")

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
        for change in ({"autoriza_contato": False}, {"cidade": " "}, {"uf": "ZZ"}, {"segmento": "invalido"},
                       {"whatsapp": "12345"}, {"nome_empresa": "  "}, {"objetivo": " " * 30},
                       {"canais": []}, {"canais": ["email"]}, {"servicos": []}, {"servicos": ["invalido"]},
                       {"servicos": ["reformulacao_site"]}, {"site_atual": "javascript:alert(1)"},
                       {"site_atual": "https://user:password@example.com"}, {"site_extra": "spam"}, {"extra": "field"}):
            response = self.client.post("/publico/aplicacoes", json=application(**change))
            self.assertEqual(response.status_code, 422, change)
        self.assertEqual(self.client.post("/publico/aplicacoes", json=application(), headers={"Origin": "https://other.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/publico/aplicacoes", content="x" * 17000, headers={"Content-Type": "application/json"}).status_code, 413)
        self.assertEqual(self.client.post("/publico/aplicacoes", content="text").status_code, 415)

    def test_nationwide_project_without_support_and_customer_conversion_guard(self):
        identifier = self.submit(application(cidade="Rio de Janeiro", uf="RJ", segmento="outro",
            servicos=["criacao_site", "sistema"], canais=[], objetivo="Criar um site e organizar os processos financeiros."))
        row = self.client.get("/v1/funil", headers=HEADERS).json()["aplicacoes"][0]
        self.assertEqual(row["servicos"], ["criacao_site", "sistema"])
        self.assertEqual(row["uf"], "RJ")
        self.assertEqual(row["canais"], [])
        self.assertEqual(row["volume"], "nao_informado")
        self.assertFalse(row["abordagem_disponivel"])
        path = "/v1/funil/" + identifier
        self.client.patch(path, headers=HEADERS, json={"etapa": "ganha", "notas": "Entregar site e sistema financeiro."}).raise_for_status()
        self.assertEqual(self.client.post(path + "/cliente", headers=HEADERS, json={"nome": "Projeto web"}).status_code, 409)
        self.assertEqual(self.client.post(path + "/empresa", headers=HEADERS).status_code, 409)
        with self.app.state.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(ApplicationProject)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(SupportTenant)), 0)

    def test_reformulation_stores_website_and_multiple_services(self):
        body = application(cidade="Curitiba", uf="PR", servicos=["reformulacao_site", "atendimento_ia"],
                           site_atual="https://empresa.example.invalid/servicos")
        identifier = self.submit(body)
        self.assertEqual(self.submit(body), identifier)
        row = self.client.get("/v1/funil", headers=HEADERS).json()["aplicacoes"][0]
        self.assertEqual(row["site_atual"], body["site_atual"])
        self.assertEqual(row["servicos"], body["servicos"])
        self.assertFalse(row["abordagem_disponivel"])
        path = "/v1/funil/" + identifier
        self.client.patch(path, headers=HEADERS, json={"etapa": "ganha"}).raise_for_status()
        self.assertEqual(self.client.post(path + "/cliente", headers=HEADERS, json={"nome": "Cliente de Curitiba"}).status_code, 200)

    def test_legacy_research_application_retains_support_behavior(self):
        with self.app.state.sessions() as session:
            session.add(SalesApplication(name="Empresa antiga", city="Campinas", segment="servicos", channels=["whatsapp"]))
            session.commit()
        row = self.client.get("/v1/funil", headers=HEADERS).json()["aplicacoes"][0]
        self.assertEqual(row["servicos"], ["atendimento_ia"])
        self.assertEqual(row["uf"], "SP")
        self.assertTrue(row["abordagem_disponivel"])
        catalog = self.client.get("/publico/aplicacoes/catalogo").json()
        self.assertEqual(len(catalog["estados"]), 27)
        self.assertEqual(len(catalog["servicos"]), 4)
        self.assertNotIn("cidades", catalog)
        self.assertEqual(len(self.client.get("/v1/cidades", headers=HEADERS).json()["cidades"]), 20)

    def test_upgrade_creates_project_table_and_preserves_existing_applications(self):
        with TemporaryDirectory() as directory:
            url = f"sqlite:///{directory}/legacy.db"
            engine = create_engine(url)
            Base.metadata.create_all(engine, tables=[table for table in Base.metadata.sorted_tables if table.name != "application_projects"])
            old_columns = [column["name"] for column in inspect(engine).get_columns("sales_applications")]
            with Session(engine) as session:
                session.add(SalesApplication(name="Cliente da versão anterior", city="Campinas", segment="restaurantes", channels=["whatsapp"]))
                session.commit()
            updated = create_app(Settings(environment="test", database_url=url, admin_api_key=KEY))
            with TestClient(updated) as client:
                rows = client.get("/v1/funil", headers=HEADERS).json()["aplicacoes"]
                self.assertEqual(rows[0]["nome_empresa"], "Cliente da versão anterior")
                self.assertEqual(rows[0]["servicos"], ["atendimento_ia"])
                response = client.post("/publico/aplicacoes", json=application(cidade="Salvador", uf="BA", servicos=["sistema"], canais=[]))
                self.assertEqual(response.status_code, 201)
            self.assertEqual([column["name"] for column in inspect(engine).get_columns("sales_applications")], old_columns)
            self.assertIn("application_projects", inspect(engine).get_table_names())
            engine.dispose()

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
