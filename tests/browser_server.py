"""Servidor descartável do teste do painel; não é importado pelo aplicativo publicado."""
from contextlib import asynccontextmanager
import os
from tempfile import TemporaryDirectory

from atendeai.api import create_app
from atendeai.config import Settings
from atendeai.models import SupportKnowledge
from atendeai.support_routes import TenantCreate

KEY = "browser-test-administrative-key-not-a-real-secret"
port = int(os.getenv("PANEL_TEST_PORT", "8136"))
origin = f"http://127.0.0.1:{port}"
directory = TemporaryDirectory(prefix="atendeai-painel-test-")
app = create_app(Settings(environment="development", database_url=f"sqlite:///{directory.name}/test.db",
                          admin_api_key=KEY, support_demo_enabled=False))
original_lifespan = app.router.lifespan_context
fixtures = {}


@asynccontextmanager
async def lifespan(application):
    async with original_lifespan(application):
        service = application.state.support
        first = service.create_tenant(TenantCreate(nome="Oficina Horizonte · teste", origens_permitidas=[origin]))
        second = service.create_tenant(TenantCreate(nome="Loja Aurora · teste", origens_permitidas=[origin]))
        with service.sessions() as session:
            session.add(SupportKnowledge(tenant_id=first["id"], title="Horário de atendimento",
                content="Atendemos de segunda a sexta, das 9h às 18h."))
            session.add(SupportKnowledge(tenant_id=second["id"], title="Resposta exclusiva da Aurora",
                content="Esta informação pertence somente à Loja Aurora."))
            session.commit()
        fixtures.update(first=first, second=second)
        yield


app.router.lifespan_context = lifespan


@app.get("/__test__/fixtures")
def test_fixtures():
    return fixtures
