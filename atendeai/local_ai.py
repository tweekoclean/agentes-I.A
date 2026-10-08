"""Inferência local compartilhada pelos três agentes; nenhum provedor pago."""
import json
import threading

import httpx


class LocalAIError(ValueError):
    pass


# Os trabalhadores e a pesquisa compartilham a mesma capacidade de inferência.
# Cada implantação deve executar um único processo Uvicorn.
INFERENCE_SLOT = threading.BoundedSemaphore(1)


def context_fits(settings, instructions, data, schema):
    content = json.dumps(data, ensure_ascii=False)
    system = instructions + " Responda somente com JSON válido conforme este esquema: " + json.dumps(schema, ensure_ascii=False)
    return len(system) + len(content) <= (settings.local_ai_context - settings.local_ai_max_tokens - 256) * 2


def generate_json(settings, instructions, data, schema, transport=None):
    if not settings.ai_configured:
        raise LocalAIError("IA local desabilitada.")
    content = json.dumps(data, ensure_ascii=False)
    system = instructions + " Responda somente com JSON válido conforme este esquema: " + json.dumps(schema, ensure_ascii=False)
    # Limite conservador de entrada; não descartamos silenciosamente políticas da empresa.
    if not context_fits(settings, instructions, data, schema):
        raise LocalAIError("Informações excedem o contexto do modelo local.")
    body = {"model": settings.local_ai_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "stream": False, "think": False, "format": schema, "keep_alive": "5m",
            "options": {"temperature": 0, "num_ctx": settings.local_ai_context,
                        "num_predict": settings.local_ai_max_tokens, "num_thread": settings.local_ai_threads}}
    if not INFERENCE_SLOT.acquire(timeout=2):
        raise LocalAIError("Servidor local ocupado.")
    try:
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
