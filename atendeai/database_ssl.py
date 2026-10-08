"""Materializa certificados privados apenas durante a execução da aplicação."""
import base64
import binascii
from pathlib import Path
import ssl
from tempfile import TemporaryDirectory

from sqlalchemy.engine import make_url

from .config import Settings


class DatabaseSSL:
    def __init__(self, settings: Settings, database_url: str):
        self.connect_args = {}
        self._directory = None
        settings.validated()
        combined = settings.database_ssl_pem_b64.strip()
        values = {
            "sslrootcert": (settings.database_ssl_ca_b64, "DATABASE_SSL_CA_B64"),
            "sslcert": (settings.database_ssl_cert_b64, "DATABASE_SSL_CERT_B64"),
            "sslkey": (settings.database_ssl_key_b64, "DATABASE_SSL_KEY_B64"),
        }
        if not combined and not any(value.strip() for value, _ in values.values()):
            return
        parsed = make_url(database_url)
        self._directory = TemporaryDirectory(prefix="atendeai-db-ssl-")
        try:
            if combined:
                path = self._write("certificate.pem", combined, "DATABASE_SSL_PEM_B64")
                paths = {name: str(path) for name in values}
            else:
                paths = {name: str(self._write(name + ".pem", value, variable))
                         for name, (value, variable) in values.items()}

            # Verifica o PEM e a correspondência entre certificado e chave sem rede.
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            try:
                context.load_verify_locations(cafile=paths["sslrootcert"])
            except ssl.SSLError:
                raise ValueError("O certificado de CA do banco não contém um PEM válido.") from None
            try:
                # Evita prompts interativos para chaves criptografadas.
                context.load_cert_chain(paths["sslcert"], paths["sslkey"], password=lambda: "")
            except ssl.SSLError:
                raise ValueError("Certificado/chave do banco inválidos, incompatíveis ou protegidos por senha.") from None

            # Mantém verify-full se a URL já pedir verificação do nome do servidor.
            mode = settings.database_ssl_mode or (
                "verify-full" if parsed.query.get("sslmode") == "verify-full" else "verify-ca")
            self.connect_args = {"sslmode": mode, **paths}
        except Exception:
            self.close()
            raise

    def _write(self, filename: str, encoded: str, variable: str):
        try:
            content = base64.b64decode("".join(encoded.split()), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError(f"{variable} precisa conter o arquivo completo em Base64 válido.") from None
        if not content:
            raise ValueError(f"{variable} não pode representar um arquivo vazio.")
        path = Path(self._directory.name) / filename
        # O diretório é privado (0700); os arquivos são privados (0600).
        with path.open("xb") as handle:
            path.chmod(0o600)
            handle.write(content)
        return path

    def close(self):
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
