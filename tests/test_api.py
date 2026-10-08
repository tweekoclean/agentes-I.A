from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import unittest

from fastapi.testclient import TestClient
import httpx
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from atendeai.api import create_app
from atendeai.catalog import resolve_city
from atendeai.config import Settings
from atendeai.models import Base
from atendeai.sources import OverpassSource, build_query, normalize_phone, parse_elements


KEY = "test-admin-key-not-a-real-secret"
HEADERS = {"X-API-Key": KEY}


def sample_payload():
    # Fabricated fixtures served only by MockTransport, not real OSM records.
    return {"elements": [
        {"type": "node", "id": 101, "tags": {"name": "Oficina Teste A", "shop": "car_repair", "addr:city": "Campinas", "addr:state": "SP", "phone": "+55 19 91234-5678", "website": "example.invalid"}},
        {"type": "way", "id": 102, "tags": {"name": "Oficina Teste B", "shop": "car_repair", "addr:city": "Campinas", "phone": "+55 19 91234-5678"}},
        {"type": "node", "id": 103, "tags": {"name": "Fora do estado", "shop": "car_repair", "addr:state": "MG"}},
        {"type": "node", "id": 104, "tags": {"name": "Outra cidade", "shop": "car_repair", "addr:city": "Santos"}},
    ]}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(environment="test", database_url="sqlite:///:memory:", admin_api_key=KEY,
                                 provider_interval_seconds=1)
        self.payload = sample_payload()
        self.calls = []

        def handler(request):
            self.calls.append(request)
            return httpx.Response(200, json=self.payload)

        self.source = OverpassSource("https://example.invalid/interpreter", httpx.MockTransport(handler))
        self.app = create_app(self.settings, source=self.source)
        self.client_context = TestClient(self.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def search(self, **changes):
        return self.client.post("/v1/buscas", headers=HEADERS,
                                json={"cidade": "Campinas", "segmentos": ["oficinas"], "limite": 20, **changes})

    def test_admin_authentication(self):
        self.assertEqual(self.client.get("/v1/empresas").status_code, 401)
        self.assertEqual(self.client.post("/v1/buscas", json={}).status_code, 401)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_geographic_scope_and_injection_rejected_before_source(self):
        for city in ["Santos", "Rio de Janeiro", 'Campinas\";out;']:
            self.assertEqual(self.search(cidade=city).status_code, 422)
        self.assertEqual(len(self.calls), 0)
        self.assertEqual(self.search(cidade="CAMPINAS").status_code, 200)
        self.assertEqual(self.client.get("/v1/cidades", headers=HEADERS).json()["uf"], "SP")

    def test_source_provenance_filter_and_shared_phone_branches(self):
        result = self.search().json()
        self.assertEqual(result["encontradas"], 2)
        rows = self.client.get("/v1/empresas", headers=HEADERS).json()["empresas"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["cidade"], "Campinas")
            self.assertTrue(row["url_fonte"].startswith("https://www.openstreetmap.org/"))
            self.assertFalse(row["telefone_publicado_confirmado_como_whatsapp"])
            self.assertFalse(row["elegivel_para_etapa_comercial"])

    def test_cached_search_does_not_duplicate_or_call_provider(self):
        first = self.search().json()
        second = self.search().json()
        self.assertEqual(first["novas"], 2)
        self.assertEqual(second["novas"], 0)
        self.assertEqual(second["ja_cadastradas"], 2)
        self.assertTrue(second["cache"])
        self.assertEqual(first["dados_consultados_em"], second["dados_consultados_em"])
        self.assertEqual(len(self.calls), 1)

    def test_published_phone_and_review_do_not_grant_consent(self):
        lead_id = self.search().json()["empresas_ids"][0]
        review = self.client.post(f"/v1/empresas/{lead_id}/revisao", headers=HEADERS,
                                  json={"status": "aprovada"}).json()
        self.assertEqual(review["consentimento_whatsapp"], "desconhecido")
        self.assertEqual(self.client.get("/v1/comercial/fila", headers=HEADERS).json()["quantidade"], 0)

    def test_consent_queue_revocation_and_stale_events(self):
        lead_id = self.search().json()["empresas_ids"][0]
        url = f"/v1/empresas/{lead_id}/consentimento"
        self.client.post(f"/v1/empresas/{lead_id}/revisao", headers=HEADERS, json={"status": "aprovada"})
        occurred = datetime.now(timezone.utc) - timedelta(minutes=10)
        body = {"status": "concedido", "destinatario_whatsapp": "+5519912345678",
                "evidencia": "Registro de formulário de teste, autorização para ofertas de atendimento IA.",
                "ocorrido_em": occurred.isoformat()}
        granted = self.client.post(url, headers=HEADERS, json=body)
        self.assertEqual(granted.status_code, 200)
        self.assertTrue(granted.json()["elegivel_para_etapa_comercial"])
        self.assertEqual(self.client.get("/v1/comercial/fila", headers=HEADERS).json()["quantidade"], 1)
        self.search()
        self.assertTrue(self.client.get(f"/v1/empresas/{lead_id}", headers=HEADERS).json()["elegivel_para_etapa_comercial"])
        revoked_body = {**body, "status": "revogado", "ocorrido_em": (occurred + timedelta(minutes=1)).isoformat()}
        self.assertEqual(self.client.post(url, headers=HEADERS, json=revoked_body).status_code, 200)
        self.assertEqual(self.client.get("/v1/comercial/fila", headers=HEADERS).json()["quantidade"], 0)
        self.assertEqual(self.client.post(url, headers=HEADERS, json=body).status_code, 409)
        self.assertEqual(self.client.get(f"/v1/empresas/{lead_id}", headers=HEADERS).json()["consentimento_whatsapp"], "revogado")

    def test_future_naive_and_invalid_recipient_events_rejected(self):
        lead_id = self.search().json()["empresas_ids"][0]
        body = {"status": "concedido", "destinatario_whatsapp": "+5519912345678", "evidencia": "Formulário de teste com aceite explícito de ofertas."}
        for timestamp in [datetime.now().isoformat(), (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()]:
            response = self.client.post(f"/v1/empresas/{lead_id}/consentimento", headers=HEADERS,
                                        json={**body, "ocorrido_em": timestamp})
            self.assertEqual(response.status_code, 422)
        response = self.client.post(f"/v1/empresas/{lead_id}/consentimento", headers=HEADERS,
                                    json={**body, "destinatario_whatsapp": "telefone ausente"})
        self.assertEqual(response.status_code, 422)

    def test_discarded_company_leaves_queue(self):
        lead_id = self.search().json()["empresas_ids"][0]
        self.client.post(f"/v1/empresas/{lead_id}/revisao", headers=HEADERS, json={"status": "descartada"})
        self.assertEqual(self.client.get("/v1/comercial/fila", headers=HEADERS).json()["quantidade"], 0)

    def test_optional_ai_fallback_is_explicitly_not_ai(self):
        lead_id = self.search().json()["empresas_ids"][0]
        response = self.client.post(f"/v1/empresas/{lead_id}/analise", headers=HEADERS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["analise"]["modo"], "regras_sem_ia")

    def test_provider_cooldown(self):
        self.search()
        response = self.search(limite=21)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)
        self.assertEqual(len(self.calls), 1)


class OtherTests(unittest.TestCase):
    def test_demo_cannot_become_commercial_contact(self):
        settings = Settings(environment="test", database_url="sqlite:///:memory:", admin_api_key=KEY)
        with TestClient(create_app(settings)) as client:
            result = client.post("/v1/buscas", headers=HEADERS, json={}).json()
            lead_id = result["empresas_ids"][0]
            client.post(f"/v1/empresas/{lead_id}/revisao", headers=HEADERS, json={"status": "aprovada"})
            response = client.post(f"/v1/empresas/{lead_id}/consentimento", headers=HEADERS, json={
                "status": "concedido", "destinatario_whatsapp": "+5519912345678",
                "evidencia": "Autorização fictícia para um teste de demonstração.",
            })
            self.assertEqual(response.status_code, 409)
            self.assertEqual(client.get("/v1/comercial/fila", headers=HEADERS).json()["quantidade"], 0)

    def test_provider_failure_does_not_invent_records(self):
        def handler(request):
            return httpx.Response(503, text="temporarily unavailable")
        source = OverpassSource("https://example.invalid", httpx.MockTransport(handler))
        settings = Settings(environment="test", database_url="sqlite:///:memory:", admin_api_key=KEY)
        with TestClient(create_app(settings, source=source)) as client:
            response = client.post("/v1/buscas", headers=HEADERS, json={})
            self.assertEqual(response.status_code, 502)
            self.assertEqual(client.get("/v1/empresas", headers=HEADERS).json()["total"], 0)

    def test_ai_schema_and_decisions_remain_separate(self):
        result = {"resumo": "Oficina em Campinas", "hipotese_de_valor": "Pode ajudar com dúvidas frequentes.",
                  "perguntas_para_validar": ["Como atendem hoje?"]}

        def handler(request):
            body = json.loads(request.content)
            self.assertFalse(body["store"])
            self.assertEqual(body["text"]["format"]["type"], "json_schema")
            self.assertNotIn("91234", body["input"])
            return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(result)}]}]})

        source = OverpassSource("https://example.invalid", httpx.MockTransport(lambda request: httpx.Response(200, json=sample_payload())))
        settings = Settings(environment="test", database_url="sqlite:///:memory:", admin_api_key=KEY, openai_api_key="fake-test-key")
        with TestClient(create_app(settings, source, httpx.MockTransport(handler))) as client:
            lead_id = client.post("/v1/buscas", headers=HEADERS, json={"segmentos": ["oficinas"]}).json()["empresas_ids"][0]
            response = client.post(f"/v1/empresas/{lead_id}/analise", headers=HEADERS)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["analise"]["modo"], "ia")
            self.assertEqual(client.get(f"/v1/empresas/{lead_id}", headers=HEADERS).json()["consentimento_whatsapp"], "desconhecido")

    def test_phone_normalization_never_combines_numbers(self):
        self.assertEqual(normalize_phone("(19) 91234-5678"), "+5519912345678")
        self.assertIsNone(normalize_phone("+55 19 91234-5678; +55 19 3234-5678"))
        self.assertIsNone(normalize_phone("+1 415 555 1234"))
        self.assertIsNone(normalize_phone("123"))

    def test_production_rejects_ephemeral_database_and_example_key(self):
        with self.assertRaises(ValueError):
            Settings(environment="production").validated()
        self.assertTrue(Settings(database_url="postgresql://user:password@localhost/db").validated().startswith("postgresql+psycopg://"))

    def test_postgresql_schema_compiles(self):
        ddl = "\n".join(str(CreateTable(table).compile(dialect=postgresql.dialect())) for table in Base.metadata.sorted_tables)
        self.assertIn("TIMESTAMP WITH TIME ZONE", ddl)
        self.assertIn("uq_lead_source", ddl)
        self.assertIn("FOREIGN KEY", ddl)

    def test_query_uses_municipal_code_not_telephone_area_code(self):
        query = build_query(resolve_city("Campinas"), ["oficinas"], 20)
        self.assertIn('"IBGE:GEOCODIGO"="3509502"', query)
        self.assertIn('"ISO3166-2"="BR-SP"', query)

    def test_partial_upstream_results_rejected(self):
        with self.assertRaises(Exception):
            parse_elements({"elements": [], "remark": "runtime error: Query timed out"}, resolve_city("Campinas"), ["oficinas"], 10)


if __name__ == "__main__":
    unittest.main()
