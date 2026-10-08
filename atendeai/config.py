from dataclasses import dataclass, field
import json
import os
import re
from urllib.parse import urlsplit

from dotenv import load_dotenv
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    database_url: str = field(default="sqlite:///./leads.db", repr=False)
    admin_api_key: str = field(default="local-demo-key-change-me", repr=False)
    search_provider: str = "demo"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    cache_hours: int = 24
    provider_interval_seconds: int = 60
    ai_provider: str = "none"
    local_ai_url: str = field(default="http://127.0.0.1:11434", repr=False)
    local_ai_model: str = "qwen3:4b"
    local_ai_token: str = field(default="", repr=False)
    local_ai_autostart: bool = False
    local_ai_directory: str = ".local-ai"
    local_ai_timeout: int = 120
    local_ai_context: int = 4096
    local_ai_max_tokens: int = 512
    local_ai_threads: int = 2
    database_ssl_pem_b64: str = field(default="", repr=False)
    database_ssl_ca_b64: str = field(default="", repr=False)
    database_ssl_cert_b64: str = field(default="", repr=False)
    database_ssl_key_b64: str = field(default="", repr=False)
    database_ssl_mode: str = ""
    whatsapp_enabled: bool = False
    whatsapp_token: str = field(default="", repr=False)
    whatsapp_phone_number_id: str = ""
    whatsapp_app_secret: str = field(default="", repr=False)
    whatsapp_verify_token: str = field(default="", repr=False)
    whatsapp_api_version: str = "v24.0"
    whatsapp_template_name: str = "atendeai_apresentacao"
    whatsapp_template_language: str = "pt_BR"
    commercial_auto_reply: bool = True
    commercial_daily_limit: int = 100
    commercial_max_auto_replies: int = 6
    support_whatsapp_accounts: dict = field(default_factory=dict, repr=False)
    support_demo_enabled: bool = True

    @classmethod
    def from_env(cls):
        load_dotenv(override=False)
        return cls(
            environment=os.getenv("APP_ENV", "development"),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./leads.db"),
            admin_api_key=os.getenv("ADMIN_API_KEY", "local-demo-key-change-me"),
            search_provider=os.getenv("SEARCH_PROVIDER", "demo"),
            overpass_url=os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter"),
            cache_hours=int(os.getenv("SEARCH_CACHE_HOURS", "24")),
            provider_interval_seconds=int(os.getenv("PROVIDER_INTERVAL_SECONDS", "60")),
            ai_provider=os.getenv("AI_PROVIDER", "none").strip().lower(),
            local_ai_url=os.getenv("LOCAL_AI_URL", "http://127.0.0.1:11434").rstrip("/"),
            local_ai_model=os.getenv("LOCAL_AI_MODEL", "qwen3:4b"),
            local_ai_token=os.getenv("LOCAL_AI_TOKEN", ""),
            local_ai_autostart=env_bool("LOCAL_AI_AUTOSTART", False),
            local_ai_directory=os.getenv("LOCAL_AI_DIRECTORY", ".local-ai"),
            local_ai_timeout=int(os.getenv("LOCAL_AI_TIMEOUT", "120")),
            local_ai_context=int(os.getenv("LOCAL_AI_CONTEXT", "4096")),
            local_ai_max_tokens=int(os.getenv("LOCAL_AI_MAX_TOKENS", "512")),
            local_ai_threads=int(os.getenv("LOCAL_AI_THREADS", "2")),
            database_ssl_pem_b64=os.getenv("DATABASE_SSL_PEM_B64", ""),
            database_ssl_ca_b64=os.getenv("DATABASE_SSL_CA_B64", ""),
            database_ssl_cert_b64=os.getenv("DATABASE_SSL_CERT_B64", ""),
            database_ssl_key_b64=os.getenv("DATABASE_SSL_KEY_B64", ""),
            database_ssl_mode=os.getenv("DATABASE_SSL_MODE", ""),
            whatsapp_enabled=env_bool("WHATSAPP_ENABLED", False),
            whatsapp_token=os.getenv("WHATSAPP_TOKEN", ""),
            whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
            whatsapp_app_secret=os.getenv("WHATSAPP_APP_SECRET", ""),
            whatsapp_verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
            whatsapp_api_version=os.getenv("WHATSAPP_API_VERSION", "v24.0"),
            whatsapp_template_name=os.getenv("WHATSAPP_TEMPLATE_NAME", "atendeai_apresentacao"),
            whatsapp_template_language=os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "pt_BR"),
            commercial_auto_reply=env_bool("COMMERCIAL_AUTO_REPLY", True),
            commercial_daily_limit=int(os.getenv("COMMERCIAL_DAILY_LIMIT", "100")),
            commercial_max_auto_replies=int(os.getenv("COMMERCIAL_MAX_AUTO_REPLIES", "6")),
            support_whatsapp_accounts=parse_support_accounts(os.getenv("SUPPORT_WHATSAPP_ACCOUNTS_JSON", "{}")),
            support_demo_enabled=env_bool("SUPPORT_DEMO_ENABLED", True),
        )

    def whatsapp_missing(self):
        return [name for name, value in {
            "WHATSAPP_TOKEN": self.whatsapp_token,
            "WHATSAPP_PHONE_NUMBER_ID": self.whatsapp_phone_number_id,
            "WHATSAPP_APP_SECRET": self.whatsapp_app_secret,
            "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_token,
        }.items() if not value.strip()]

    @property
    def whatsapp_ready(self):
        return self.whatsapp_enabled and not self.whatsapp_missing()

    @property
    def ai_configured(self):
        return self.ai_provider == "ollama"

    @property
    def local_ai_headers(self):
        return {"Authorization": "Bearer " + self.local_ai_token} if self.local_ai_token else {}

    def validated(self):
        if self.environment not in {"development", "production", "test"}:
            raise ValueError("APP_ENV deve ser development, production ou test.")
        if self.ai_provider not in {"none", "ollama"}:
            raise ValueError("AI_PROVIDER deve ser none ou ollama. Este projeto usa somente IA local.")
        endpoint = urlsplit(self.local_ai_url)
        loopback = endpoint.hostname in {"127.0.0.1", "localhost", "::1"}
        if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username
                or endpoint.password or endpoint.query or endpoint.fragment
                or (endpoint.scheme == "http" and not loopback)):
            raise ValueError("LOCAL_AI_URL exige HTTPS ou HTTP em localhost, sem credenciais na URL.")
        if endpoint.hostname == "ollama.com" or (endpoint.hostname or "").endswith(".ollama.com"):
            raise ValueError("Use seu servidor local, não o serviço de nuvem da Ollama.")
        if self.ai_configured and not loopback and not self.local_ai_token:
            raise ValueError("Seu servidor remoto de IA precisa de LOCAL_AI_TOKEN e proteção de acesso.")
        if not re.fullmatch(r"[a-zA-Z0-9_.:/-]{1,120}", self.local_ai_model) or "cloud" in self.local_ai_model.lower():
            raise ValueError("LOCAL_AI_MODEL deve ser um modelo local, sem versões cloud.")
        if self.local_ai_autostart and (not self.ai_configured or not loopback or endpoint.path not in {"", "/"}
                or endpoint.port not in {None, 11434} or endpoint.scheme != "http"):
            raise ValueError("LOCAL_AI_AUTOSTART exige AI_PROVIDER=ollama e http://127.0.0.1:11434.")
        if self.local_ai_autostart and self.local_ai_model not in {"qwen3:0.6b", "qwen3:1.7b", "qwen3:4b"}:
            raise ValueError("Autostart suporta qwen3:0.6b, qwen3:1.7b e qwen3:4b. Outros modelos exigem servidor externo.")
        if not 10 <= self.local_ai_timeout <= 150 or not 2048 <= self.local_ai_context <= 8192:
            raise ValueError("LOCAL_AI_TIMEOUT deve ser 10 a 150; LOCAL_AI_CONTEXT, 2048 a 8192.")
        if not 128 <= self.local_ai_max_tokens <= 1024 or not 1 <= self.local_ai_threads <= 8:
            raise ValueError("LOCAL_AI_MAX_TOKENS deve ser 128 a 1024; LOCAL_AI_THREADS, 1 a 8.")
        if self.search_provider not in {"demo", "overpass"}:
            raise ValueError("SEARCH_PROVIDER deve ser demo ou overpass.")
        if not self.overpass_url.startswith("https://"):
            raise ValueError("OVERPASS_URL precisa usar HTTPS.")
        if not 1 <= self.cache_hours <= 720:
            raise ValueError("SEARCH_CACHE_HOURS deve estar entre 1 e 720.")
        if not 0 <= self.provider_interval_seconds <= 86400:
            raise ValueError("PROVIDER_INTERVAL_SECONDS inválido.")
        if not re.fullmatch(r"v\d{1,2}\.\d", self.whatsapp_api_version):
            raise ValueError("WHATSAPP_API_VERSION deve ter o formato v24.0.")
        if self.whatsapp_phone_number_id and not re.fullmatch(r"\d{5,25}", self.whatsapp_phone_number_id):
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID é o ID numérico da Meta, não o telefone.")
        if not re.fullmatch(r"[a-z0-9_]{1,100}", self.whatsapp_template_name):
            raise ValueError("WHATSAPP_TEMPLATE_NAME deve conter letras minúsculas, números ou sublinhado.")
        if not re.fullmatch(r"[a-z]{2}(?:_[A-Z]{2})?", self.whatsapp_template_language):
            raise ValueError("WHATSAPP_TEMPLATE_LANGUAGE inválido.")
        if not 1 <= self.commercial_daily_limit <= 1000 or not 1 <= self.commercial_max_auto_replies <= 30:
            raise ValueError("Limite comercial deve ser 1 a 1000; respostas automáticas, 1 a 30.")
        validate_support_accounts(self.support_whatsapp_accounts, self.whatsapp_phone_number_id)
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        parsed = make_url(url)
        if parsed.drivername not in {"postgresql+psycopg", "sqlite"}:
            raise ValueError("Use PostgreSQL ou SQLite para desenvolvimento.")
        if self.database_ssl_mode not in {"", "verify-ca", "verify-full"}:
            raise ValueError("DATABASE_SSL_MODE deve ser verify-ca ou verify-full.")
        combined = bool(self.database_ssl_pem_b64.strip())
        separate = [bool(value.strip()) for value in (
            self.database_ssl_ca_b64, self.database_ssl_cert_b64, self.database_ssl_key_b64)]
        if combined or any(separate):
            if parsed.drivername != "postgresql+psycopg":
                raise ValueError("Certificados DATABASE_SSL_* exigem PostgreSQL.")
            if combined and any(separate):
                raise ValueError("Use DATABASE_SSL_PEM_B64 ou as três variáveis separadas, sem misturá-las.")
            if not combined and not all(separate):
                raise ValueError("Informe DATABASE_SSL_CA_B64, DATABASE_SSL_CERT_B64 e DATABASE_SSL_KEY_B64 juntas.")
        if len(self.admin_api_key) < 16:
            raise ValueError("ADMIN_API_KEY precisa ter pelo menos 16 caracteres.")
        if self.environment == "production":
            if parsed.drivername != "postgresql+psycopg":
                raise ValueError("Produção exige DATABASE_URL de um PostgreSQL persistente.")
            if len(self.admin_api_key) < 32 or self.admin_api_key == Settings.admin_api_key:
                raise ValueError("Produção exige ADMIN_API_KEY própria, com 32 caracteres ou mais.")
            if self.search_provider == "demo":
                raise ValueError("Produção exige SEARCH_PROVIDER=overpass.")
        return url


def env_bool(name, default):
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} deve ser true ou false.")
    return value in {"true", "1"}



def parse_support_accounts(value):
    try:
        result = json.loads(value)
        validate_support_accounts(result)
        return result
    except (ValueError, TypeError):
        raise ValueError("SUPPORT_WHATSAPP_ACCOUNTS_JSON inválido. Confira IDs e credenciais sem publicá-los.") from None


def validate_support_accounts(accounts, commercial_id=""):
    if not isinstance(accounts, dict):
        raise ValueError("SUPPORT_WHATSAPP_ACCOUNTS_JSON deve ser um objeto JSON.")
    used = {commercial_id} if commercial_id else set()
    for tenant_id, account in accounts.items():
        if not isinstance(tenant_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", tenant_id) or not isinstance(account, dict):
            raise ValueError("Cada conta de suporte precisa do ID da empresa e de um objeto de configuração.")
        if set(account) - {"enabled", "token", "phone_number_id", "app_secret", "verify_token", "api_version"}:
            raise ValueError("Campo desconhecido em SUPPORT_WHATSAPP_ACCOUNTS_JSON.")
        if not isinstance(account.get("enabled", False), bool):
            raise ValueError("enabled da conta WhatsApp precisa ser booleano JSON.")
        for name in ["token", "phone_number_id", "app_secret", "verify_token", "api_version"]:
            if name in account and not isinstance(account[name], str):
                raise ValueError("Credenciais da conta WhatsApp precisam ser textos.")
        phone_id = account.get("phone_number_id", "")
        if phone_id and not re.fullmatch(r"\d{5,25}", phone_id):
            raise ValueError("phone_number_id do suporte precisa ser um ID numérico da Meta.")
        if not re.fullmatch(r"v\d{1,2}\.\d", account.get("api_version", "v24.0")):
            raise ValueError("Versão da API WhatsApp de suporte inválida.")
        if phone_id in used:
            raise ValueError("Cada número WhatsApp deve pertencer a um único módulo e empresa.")
        if phone_id:
            used.add(phone_id)
        if account.get("enabled", False) and any(not account.get(name, "").strip() for name in
                ["token", "phone_number_id", "app_secret", "verify_token"]):
            raise ValueError("Conta WhatsApp de suporte habilitada exige as quatro credenciais.")
