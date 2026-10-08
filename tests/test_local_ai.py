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
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import httpx
import zstandard

from atendeai.api import create_app
from atendeai.config import Settings
from atendeai.local_ai import INFERENCE_SLOT, LAST_METRICS, LocalAIError, generate_json, local_ai_status
from atendeai.local_ai_runtime import LocalAIRuntime, extract_cpu_runtime
from atendeai.support_brain import decide_support

KEY = "local-ai-test-key-never-used-in-production"
SCHEMA = {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"], "additionalProperties": False}


class LocalAITests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(environment="test", database_url="sqlite:///:memory:", admin_api_key=KEY, ai_provider="ollama")
        self.metrics_patch = patch.dict(LAST_METRICS, {}, clear=True)
        self.metrics_patch.start()
        self.addCleanup(self.metrics_patch.stop)

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
            self.assertEqual(body["keep_alive"], "30m")
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
            self.assertEqual([item["id"] for item in data["base"]], ["1"])
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"acao": "responder", "texto": "Fato não fornecido", "referencias": ["2"]})}})
        decision, mode = decide_support(self.settings, SimpleNamespace(name="Teste"), knowledge, "Qual horário?", [], True, httpx.MockTransport(handler))
        self.assertEqual(decision.acao, "encaminhar")
        self.assertEqual(mode, "falha_ia")

    def test_model_admitting_missing_information_becomes_a_real_handoff(self):
        def handler(request):
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"acao": "responder", "texto": "A base não contém informações sobre esse preço.", "referencias": ["1"]})}})
        decision, mode = decide_support(self.settings, SimpleNamespace(name="Teste"),
            [{"id": "hours", "titulo": "Horário", "conteudo": "Abre às 9h."}], "Qual preço?", [], True, httpx.MockTransport(handler))
        self.assertEqual(decision.acao, "encaminhar")
        self.assertEqual(decision.referencias, [])
        self.assertEqual(mode, "ia")

    def test_short_reference_codes_map_to_only_the_documents_in_this_request(self):
        private_id = "c8a9e9d5-5634-4cee-b826-22409108d171"
        def handler(request):
            body = json.loads(request.content)
            data = json.loads(body["messages"][1]["content"])
            self.assertNotIn(private_id, request.content.decode())
            self.assertEqual(body["options"]["num_predict"], 256)
            self.assertEqual(data["base"][0]["id"], "1")
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"acao": "responder", "texto": "Abrimos às 9h.", "referencias": ["1"]})}})
        decision, mode = decide_support(self.settings, SimpleNamespace(name="Teste"),
            [{"id": private_id, "titulo": "Horário", "conteudo": "Abre às 9h."}], "Qual horário?", [], True, httpx.MockTransport(handler))
        self.assertEqual(decision.referencias, [private_id])
        self.assertEqual(mode, "ia")

    def test_metrics_expose_only_timings_and_counts_for_the_same_model_endpoint(self):
        response = {"done": True, "done_reason": "stop", "load_duration": 20_000_000,
                    "prompt_eval_duration": 50_000_000, "eval_duration": 90_000_000,
                    "prompt_eval_count": 123, "eval_count": 25,
                    "message": {"role": "assistant", "content": '{"texto":"PRIVATE_ANSWER_VALUE"}'}}
        generate_json(self.settings, "PRIVATE_INSTRUCTIONS_VALUE", {"texto": "PRIVATE_CUSTOMER_VALUE"}, SCHEMA,
                      httpx.MockTransport(lambda request: httpx.Response(200, json=response)))
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]}))
        status = local_ai_status(self.settings, transport)
        metrics = status["ultima_geracao"]
        self.assertEqual((metrics["carga_ms"], metrics["entrada_ms"], metrics["geracao_ms"]), (20, 50, 90))
        self.assertEqual((metrics["tokens_entrada"], metrics["tokens_saida"]), (123, 25))
        self.assertNotIn("PRIVATE_", json.dumps(status))
        self.assertNotIn("ultima_geracao", local_ai_status(replace(self.settings, local_ai_model="qwen3:1.7b"), transport))
        self.assertNotIn("ultima_geracao", local_ai_status(replace(self.settings, local_ai_url="https://different.example.invalid"), transport))

    def test_document_order_is_stable_between_questions_with_different_relevance(self):
        knowledge = [{"id": "second", "titulo": "Entrega", "conteudo": "Entrega no centro."},
                     {"id": "first", "titulo": "Horário", "conteudo": "Abre às 9h."}]
        documents = []
        def handler(request):
            data = json.loads(json.loads(request.content)["messages"][1]["content"])
            documents.append(data["base"])
            return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps({"acao": "responder", "texto": "Abrimos às 9h.", "referencias": ["1"]})}})
        for items, question in [(knowledge, "Qual horário?"), (knowledge[::-1], "E a entrega?")]:
            decision, mode = decide_support(self.settings, SimpleNamespace(name="Teste"), items, question, [], True, httpx.MockTransport(handler))
            self.assertEqual(decision.referencias, ["first"])
            self.assertEqual(mode, "ia")
        self.assertEqual(documents[0], documents[1])

    def test_model_retention_has_an_explicit_bound(self):
        for minutes in (0, 1441):
            with self.assertRaises(ValueError):
                replace(self.settings, local_ai_keep_alive_minutes=minutes).validated()
        replace(self.settings, local_ai_keep_alive_minutes=30).validated()

    def test_runtime_preloads_without_generating_a_customer_message(self):
        runtime = LocalAIRuntime(replace(self.settings, local_ai_autostart=True))
        client = Mock()
        client.get.return_value = httpx.Response(200, json={"version": "test"}, request=httpx.Request("GET", "http://127.0.0.1:11434/api/version"))
        client.post.return_value = httpx.Response(200, json={"done": True, "done_reason": "load"}, request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"))
        process = Mock()
        process.poll.return_value = None
        with patch("atendeai.local_ai_runtime.subprocess.Popen", return_value=process), \
             patch("atendeai.local_ai_runtime.httpx.Client") as factory, \
             patch("atendeai.local_ai_runtime.local_ai_status", return_value={"pronta": True}):
            factory.return_value.__enter__.return_value = client
            runtime.start_and_pull(Path("/fake/ollama"))
        args, kwargs = client.post.call_args
        self.assertEqual(args, ("http://127.0.0.1:11434/api/chat",))
        self.assertEqual(kwargs["json"]["messages"], [])
        self.assertEqual(kwargs["json"]["keep_alive"], "30m")
        self.assertEqual(kwargs["json"]["options"]["num_ctx"], self.settings.local_ai_context)
        self.assertEqual(runtime.state, "pronta")

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
