"""Inferência local compartilhada pelos três agentes; nenhum provedor pago."""
import json
import logging
import threading
import time
from datetime import datetime, timezone

import httpx


class LocalAIError(ValueError):
    pass


# Os trabalhadores e a pesquisa compartilham a mesma capacidade de inferência.
# Cada implantação deve executar um único processo Uvicorn.
INFERENCE_SLOT = threading.BoundedSemaphore(1)
METRICS_LOCK = threading.Lock()
LAST_METRICS = {}
logger = logging.getLogger("atendeai.ia_local")


def encode_prompt(instructions, data, schema):
    content = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    system = instructions + " Responda somente com JSON conforme: " + json.dumps(
        schema, ensure_ascii=False, separators=(",", ":"))
    return system, content


def context_fits(settings, instructions, data, schema, max_tokens=None):
    system, content = encode_prompt(instructions, data, schema)
    output_limit = min(settings.local_ai_max_tokens, max_tokens or settings.local_ai_max_tokens)
    return len(system) + len(content) <= (settings.local_ai_context - output_limit - 256) * 2


def generate_json(settings, instructions, data, schema, transport=None, *, max_tokens=None):
    if not settings.ai_configured:
        raise LocalAIError("IA local desabilitada.")
    system, content = encode_prompt(instructions, data, schema)
    output_limit = min(settings.local_ai_max_tokens, max_tokens or settings.local_ai_max_tokens)
    # Limite conservador de entrada; não descartamos silenciosamente políticas da empresa.
    if not context_fits(settings, instructions, data, schema, output_limit):
        raise LocalAIError("Informações excedem o contexto do modelo local.")
    body = {"model": settings.local_ai_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "stream": False, "think": False, "format": schema,
            "keep_alive": f"{settings.local_ai_keep_alive_minutes}m",
            "options": {"temperature": 0, "num_ctx": settings.local_ai_context,
                        "num_predict": output_limit, "num_thread": settings.local_ai_threads}}
    if not INFERENCE_SLOT.acquire(timeout=2):
        raise LocalAIError("Servidor local ocupado.")
    try:
        started = time.monotonic()
        with httpx.Client(timeout=httpx.Timeout(settings.local_ai_timeout, connect=10),
                          transport=transport, follow_redirects=False) as client:
            response = client.post(settings.local_ai_url.rstrip("/") + "/api/chat", json=body,
                                   headers=settings.local_ai_headers)
            response.raise_for_status()
            if len(response.content) > 128_000:
                raise LocalAIError("Resposta local excedeu o limite.")
            payload = response.json()
        if payload.get("done") is not True or payload.get("done_reason") != "stop":
            raise LocalAIError("Resposta local incompleta.")
        message = payload.get("message", {})
        result = message.get("content")
        if message.get("role") != "assistant" or not isinstance(result, str) or not result.strip():
            raise LocalAIError("Resposta local inválida.")
        metrics = {"registrado_em": datetime.now(timezone.utc).isoformat(),
                   "tempo_total_ms": round((time.monotonic() - started) * 1000)}
        for source, target in {"load_duration": "carga_ms", "prompt_eval_duration": "entrada_ms",
                               "eval_duration": "geracao_ms"}.items():
            value = payload.get(source)
            if type(value) is int and value >= 0:
                metrics[target] = round(value / 1_000_000)
        for source, target in {"prompt_eval_count": "tokens_entrada", "eval_count": "tokens_saida"}.items():
            value = payload.get(source)
            if type(value) is int and value >= 0:
                metrics[target] = value
        with METRICS_LOCK:
            LAST_METRICS.clear()
            LAST_METRICS[(settings.local_ai_url, settings.local_ai_model)] = metrics
        # Apenas tempos e contagens; nunca texto, histórico ou credenciais.
        logger.info("IA local: total=%s ms carga=%s ms entrada=%s ms geracao=%s ms tokens_entrada=%s tokens_saida=%s",
                    metrics["tempo_total_ms"], metrics.get("carga_ms"), metrics.get("entrada_ms"),
                    metrics.get("geracao_ms"), metrics.get("tokens_entrada"), metrics.get("tokens_saida"))
        return result
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        raise LocalAIError("Não foi possível concluir a inferência local.") from exc
    finally:
        INFERENCE_SLOT.release()


def local_ai_status(settings, transport=None):
    result = {"provedor": settings.ai_provider, "modelo": settings.local_ai_model if settings.ai_configured else None,
              "configurada": settings.ai_configured, "pronta": False, "estado": "desabilitada",
              "cobranca_por_tokens": False}
    if not settings.ai_configured:
        return result
    with METRICS_LOCK:
        metrics = LAST_METRICS.get((settings.local_ai_url, settings.local_ai_model))
        if metrics:
            result["ultima_geracao"] = dict(metrics)
    result["estado"] = "indisponivel"
    try:
        with httpx.Client(timeout=5, transport=transport, follow_redirects=False) as client:
            response = client.get(settings.local_ai_url.rstrip("/") + "/api/tags", headers=settings.local_ai_headers)
            response.raise_for_status()
            payload = response.json()
        names = {model.get("name") for model in payload.get("models", [])}
        result["pronta"] = settings.local_ai_model in names
        result["estado"] = "pronta" if result["pronta"] else "modelo_pendente"
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        pass
    return result
