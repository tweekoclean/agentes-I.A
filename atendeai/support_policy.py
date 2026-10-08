"""Regras rápidas do atendimento; decisões não dependem de frases da IA."""
import re

from .commercial_inbox import normalize_text

CONFIRMATION_PREFIX = "confirmacao_responsavel:"
ASK_HANDOFF = "Não consegui responder sua solicitação com segurança. Quer que eu chame um responsável?"
DECLINE_HANDOFF = "Tudo bem. Podemos continuar por aqui. Qual é sua próxima dúvida?"

# Perguntas gerais reconhecíveis ficam fora do atendimento, exceto quando o
# próprio negócio trabalha com esse assunto ou a mensagem contém uma solicitação
# comercial. Os outros assuntos continuam sendo classificados pelo modelo.
GENERAL_TOPICS = (
    (r"\bcapital\s+(?:do|da|de)\s+(?!giro\b|empresa\b|negocio\b|sociedade\b|investimento\b)[a-z]",
     r"\b(?:geografia|turismo|turistic\w*|viagen\w*|escola|ensino|educa\w*)\b"),
    (r"\b(?:conte|escreva|crie|faca|invente)\b.*\b(?:piada|poema|poesia|conto|historia ficticia)\b",
     r"\b(?:livr\w*|literatur\w*|editora|poesia|poema|comedia|teatro|escola|ensino)\b"),
    (r"\b(?:quem|qual)\b.*\b(?:presidente|governador)\s+(?:do|da|dos|de)\s+(?:brasil|estados unidos|sao paulo|portugal)\b",
     r"\b(?:politic\w*|eleitor\w*|govern\w*|noticia\w*|jornal\w*)\b"),
    (r"\b(?:quem ganhou|resultado d[oa]|placar d[oa]|qual o melhor)\b.*\b(?:jogo|partida|time|campeonato|copa)\b",
     r"\b(?:esport\w*|futebol|campeonato|time|noticia\w*|jornal\w*)\b"),
    (r"\b(?:quanto (?:e|da)|calcule|resolva)\b.*\d\s*[+*/x-]\s*\d",
     r"\b(?:matematic\w*|escola|ensino|educa\w*|aula\w*)\b"),
)
BUSINESS_INTENT = re.compile(
    r"\b(?:entreg\w*|atend\w*|pedido\w*|servic\w*|compr\w*|produt\w*|orcamento\w*|"
    r"reserv\w*|agend\w*|preco\w*|pagamento\w*|cardapio\w*|unidade\w*|loja\w*)\b")


def clearly_unrelated_message(text, business_context):
    value = normalize_text(text)
    if BUSINESS_INTENT.search(value):
        return False
    context = normalize_text(business_context)
    return any(re.search(question, value) and not re.search(related, context)
               for question, related in GENERAL_TOPICS)


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
