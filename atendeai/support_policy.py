"""Regras rápidas do atendimento; decisões não dependem de frases da IA."""
import re

from .commercial_inbox import normalize_text

CONFIRMATION_PREFIX = "confirmacao_responsavel:"
ASK_HANDOFF = "Não consegui responder sua solicitação com segurança. Quer que eu chame um responsável?"
DECLINE_HANDOFF = "Tudo bem. Podemos continuar por aqui. Qual é sua próxima dúvida?"


def abusive_message(text):
    value = normalize_text(text)
    if value in {"merda", "idiota", "imbecil", "vsf", "vtnc", "foda-se", "foda se"}:
        return True
    return any(re.search(pattern, value) for pattern in (
        r"\b(?:chupa(?:r)?|lambe(?:r)?)\s+(?:(?:o|a|meu|minha|seu|sua)\s+)*(?:pau|penis|pica|rola|buceta)\b",
        r"\b(?:vou|posso|quero|irei)\s+(?:te\s+matar|matar\s+(?:voce|vc|voces|vcs))\b",
        r"\bvai\s+(?:se\s+foder|tomar\s+no\s+cu)\b"))


def confirmation_reply(text):
    value = re.sub(r"[^a-z0-9\s]", " ", normalize_text(text))
    value = " ".join(value.split())
    if value in {"nao", "nn", "n", "agora nao", "nao obrigado", "nao precisa", "nao quero", "deixa pra la", "deixa para la"}:
        return False
    if re.fullmatch(r"(?:nao|nn|n)\s+(?:quero|precisa|chama|chame|chamar|obrigad[oa])\b.*", value):
        return False
    if re.search(r"\b(?:nao|nn)\b", value):
        return None
    if re.fullmatch(r"(?:sim+|s+)(?:\s+(?:pode chamar|pode encaminhar|por favor|obrigado|pode ser))?", value):
        return True
    if value in {"pode", "claro", "pode sim", "pode chamar", "pode encaminhar", "pode ser", "ok", "okay"}:
        return True
    return None


def explicit_human_request(text):
    value = normalize_text(text)
    if re.search(r"\b(?:nao|nn)\b", value):
        return False
    if value in {"atendente", "humano", "responsavel"}:
        return True
    return bool(re.search(
        r"\b(?:falar com|conversar com|chama|chame|chamar|me encaminhe para|me transfira para)\s+"
        r"(?:(?:um|uma|o|a)\s+)?(?:atendente|humano|responsavel|pessoa)\b", value))
