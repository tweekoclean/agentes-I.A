from dataclasses import dataclass, field
import os

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
    openai_api_key: str = field(default="", repr=False)
    openai_model: str = "gpt-4.1-mini"
    database_ssl_pem_b64: str = field(default="", repr=False)
    database_ssl_ca_b64: str = field(default="", repr=False)
    database_ssl_cert_b64: str = field(default="", repr=False)
    database_ssl_key_b64: str = field(default="", repr=False)
    database_ssl_mode: str = ""

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
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            database_ssl_pem_b64=os.getenv("DATABASE_SSL_PEM_B64", ""),
            database_ssl_ca_b64=os.getenv("DATABASE_SSL_CA_B64", ""),
            database_ssl_cert_b64=os.getenv("DATABASE_SSL_CERT_B64", ""),
            database_ssl_key_b64=os.getenv("DATABASE_SSL_KEY_B64", ""),
            database_ssl_mode=os.getenv("DATABASE_SSL_MODE", ""),
        )

    def validated(self):
        if self.environment not in {"development", "production", "test"}:
            raise ValueError("APP_ENV deve ser development, production ou test.")
        if self.search_provider not in {"demo", "overpass"}:
            raise ValueError("SEARCH_PROVIDER deve ser demo ou overpass.")
        if not self.overpass_url.startswith("https://"):
            raise ValueError("OVERPASS_URL precisa usar HTTPS.")
        if not 1 <= self.cache_hours <= 720:
            raise ValueError("SEARCH_CACHE_HOURS deve estar entre 1 e 720.")
        if not 0 <= self.provider_interval_seconds <= 86400:
            raise ValueError("PROVIDER_INTERVAL_SECONDS inválido.")
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
