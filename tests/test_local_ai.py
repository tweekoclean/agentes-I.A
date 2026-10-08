"""IA local: limites, falhas, isolamento e inicialização sem serviços pagos."""
import asyncio
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import httpx
import zstandard

from atendeai.api import create_app
from atendeai.config import Settings
from atendeai.local_ai import INFERENCE_SLOT, LocalAIError, generate_json, local_ai_status
from atendeai.local_ai_runtime import LocalAIRuntime, extract_cpu_runtime
from atendeai.support_brain import decide_support

KEY = "local-ai-test-key-never-used-in-production"
SCHEMA = {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"], "additionalProperties": False}


class LocalAITests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(environment="test", database_url="sqlite:///:memory:", admin_api_key=KEY, ai_provider="ollama")

    def test_legacy_paid_provider_key_cannot_enable_or_select_a_paid_provider(self):
        with patch.dict(os.environ, {"AI_PROVIDER": "none", "OPENAI_API_KEY": "unused-test-value"}):
            self.assertFalse(Settings.from_env().ai_configured)
        for name in ["openai", "ollama-cloud"]:
            with self.assertRaises(ValueError):
                replace(self.settings, ai_provider=name).validated()

    def test_remote_server_requires_https_and_private_authentication(self):
        for url in ["http://host.example.invalid", "https://user:pass@host.example.invalid", "https://host.example.invalid?token=x"]:
            with self.assertRaises(ValueError):
                replace(self.settings, local_ai_url=url).validated()
        with self.assertRaises(ValueError):
            replace(self.settings, local_ai_url="https://host.example.invalid").validated()
        self.assertTrue(replace(self.settings, local_ai_url="https://host.example.invalid", local_ai_token="fake-local-key").validated())

    def test_cloud_models_and_managed_external_hosts_are_rejected(self):
        for changes in [{"local_ai_model": "qwen3:cloud"}, {"local_ai_url": "https://ollama.com", "local_ai_token": "fake"},
                        {"local_ai_autostart": True, "local_ai_url": "https://host.example.invalid", "local_ai_token": "fake"}]:
            with self.assertRaises(ValueError):
                replace(self.settings, **changes).validated()

    def test_local_protocol_never_calls_a_paid_api_and_bounds_memory_and_output(self):
        calls = []
        def handler(request):
            calls.append(request)
            self.assertEqual(str(request.url), "http://127.0.0.1:11434/api/chat")
            body = json.loads(request.content)
            self.assertFalse(body["stream"])
            self.assertFalse(body["think"])
            self.assertEqual(body["options"]["num_ctx"], 4096)
            self.assertEqual(body["options"]["num_predict"], 512)
            self.assertEqual(body["format"], SCHEMA)
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
                "role": "assistant", "content": '{"texto":"Resposta criada localmente"}'}})
        answer = generate_json(self.settings, "Use os fatos", {"pergunta": "Horários?"}, SCHEMA, httpx.MockTransport(handler))
        self.assertEqual(json.loads(answer)["texto"], "Resposta criada localmente")
        self.assertEqual(len(calls), 1)

    def test_failed_or_truncated_answers_have_no_automatic_retry_or_cloud_fallback(self):
        for result in [httpx.Response(503), httpx.Response(200, json={"done": True, "done_reason": "length", "message": {"content": "{}"}}),
                       httpx.Response(302, headers={"Location": "https://api.openai.com/v1/responses"})]:
            calls = []
            def handler(request):
                calls.append(request)
                return result
            with self.assertRaises(LocalAIError):
                generate_json(self.settings, "Fatos", {}, SCHEMA, httpx.MockTransport(handler))
            self.assertEqual(len(calls), 1)

    def test_oversized_context_is_rejected_before_request(self):
        calls = []
        with self.assertRaises(LocalAIError):
            generate_json(self.settings, "Fatos", {"base": "a" * 15_000}, SCHEMA,
                          httpx.MockTransport(lambda request: calls.append(request)))
        self.assertEqual(calls, [])

    def test_single_inference_slot_limits_concurrent_usage(self):
        INFERENCE_SLOT.acquire()
        try:
            with self.assertRaises(LocalAIError):
                generate_json(self.settings, "Fatos", {}, SCHEMA, httpx.MockTransport(lambda request: self.fail("Requisição simultânea")))
        finally:
            INFERENCE_SLOT.release()

    def test_answer_cannot_reference_a_document_excluded_by_the_context_limit(self):
        knowledge = [{"id": "small", "titulo": "Horário", "conteudo": "Aberto até as 18h."},
                     {"id": "large", "titulo": "Documento longo", "conteudo": "x" * 9000}]
        def handler(request):
            data = json.loads(json.loads(request.content)["messages"][1]["content"])
            self.assertEqual([item["id"] for item in data["base"]], ["small"])
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"acao": "responder", "texto": "Fato não fornecido", "referencias": ["large"]})}})
        decision, mode = decide_support(self.settings, SimpleNamespace(name="Teste"), knowledge, "Qual horário?", [], True, httpx.MockTransport(handler))
        self.assertEqual(decision.acao, "encaminhar")
        self.assertEqual(mode, "falha_ia")

    def test_model_admitting_missing_information_becomes_a_real_handoff(self):
        def handler(request):
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"acao": "responder", "texto": "A base não contém informações sobre esse preço.", "referencias": ["hours"]})}})
        decision, mode = decide_support(self.settings, SimpleNamespace(name="Teste"),
            [{"id": "hours", "titulo": "Horário", "conteudo": "Abre às 9h."}], "Qual preço?", [], True, httpx.MockTransport(handler))
        self.assertEqual(decision.acao, "encaminhar")
        self.assertEqual(decision.referencias, [])
        self.assertEqual(mode, "ia")

    def test_status_distinguishes_unavailable_missing_and_installed_model_without_generation(self):
        for response, state in [(httpx.Response(503), "indisponivel"), (httpx.Response(200, json={"models": []}), "modelo_pendente"),
                                (httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]}), "pronta")]:
            def handler(request):
                self.assertEqual(request.method, "GET")
                self.assertEqual(request.url.path, "/api/tags")
                return response
            status = local_ai_status(self.settings, httpx.MockTransport(handler))
            self.assertEqual(status["estado"], state)
            self.assertEqual(status["pronta"], state == "pronta")
            self.assertFalse(status["cobranca_por_tokens"])

    def test_ai_diagnostic_endpoint_is_private_and_omits_credentials(self):
        settings = replace(self.settings, local_ai_url="https://private-host.example.invalid", local_ai_token="PRIVATE_AI_VALUE")
        transport = httpx.MockTransport(lambda request: httpx.Response(503))
        with TestClient(create_app(settings, ai_transport=transport)) as client:
            self.assertEqual(client.get("/v1/ia/status").status_code, 401)
            result = client.get("/v1/ia/status", headers={"X-API-Key": KEY})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers["Cache-Control"], "no-store")
            self.assertNotIn(settings.local_ai_token, result.text)
            self.assertNotIn(settings.local_ai_url, result.text)

    def test_managed_model_does_not_start_on_insufficient_memory(self):
        runtime = LocalAIRuntime(replace(self.settings, local_ai_autostart=True))
        with patch("atendeai.local_ai_runtime.memory_limit_mb", return_value=512), patch.object(runtime, "install") as install:
            asyncio.run(runtime.run())
        install.assert_not_called()
        self.assertEqual(runtime.state, "memoria_insuficiente")

    def test_runtime_extraction_excludes_gpu_files_and_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "test.tar.zst"
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w") as package:
                for name in ["bin/ollama", "lib/ollama/cpu/libggml.so", "lib/ollama/cuda_v12/libgpu.so"]:
                    member = tarfile.TarInfo(name)
                    member.size, member.mode = 3, 0o755
                    package.addfile(member, io.BytesIO(b"abc"))
                link = tarfile.TarInfo("lib/ollama/cpu/libggml.so.0")
                link.type, link.linkname = tarfile.SYMTYPE, "libggml.so"
                package.addfile(link)
            archive.write_bytes(zstandard.ZstdCompressor().compress(data.getvalue()))
            target = Path(directory) / "extracted"
            extract_cpu_runtime(archive, target)
            self.assertTrue((target / "bin/ollama").is_file())
            self.assertTrue((target / "lib/ollama/cpu/libggml.so").is_file())
            self.assertEqual((target / "lib/ollama/cpu/libggml.so.0").read_bytes(), b"abc")
            self.assertFalse((target / "lib/ollama/cuda_v12/libgpu.so").exists())
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w") as package:
                member = tarfile.TarInfo("../escape")
                member.size = 3
                package.addfile(member, io.BytesIO(b"abc"))
            archive.write_bytes(zstandard.ZstdCompressor().compress(data.getvalue()))
            with self.assertRaises(ValueError):
                extract_cpu_runtime(archive, target)
            self.assertFalse((Path(directory) / "escape").exists())


if __name__ == "__main__":
    unittest.main()
