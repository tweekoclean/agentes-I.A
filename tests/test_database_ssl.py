import base64
from dataclasses import replace
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from atendeai.api import create_app
from atendeai.config import Settings
from atendeai.database_ssl import DatabaseSSL
from atendeai.models import build_database


URL = "postgresql://test_user:placeholder@localhost/test"


class SettingsSSLTests(unittest.TestCase):
    def test_rejects_incomplete_mixed_and_sqlite_certificates(self):
        cases = [
            Settings(database_ssl_pem_b64="placeholder"),
            Settings(database_url=URL, database_ssl_ca_b64="placeholder"),
            Settings(database_url=URL, database_ssl_pem_b64="placeholder", database_ssl_key_b64="placeholder"),
            Settings(database_url=URL, database_ssl_mode="disable"),
        ]
        for settings in cases:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                settings.validated()

    def test_credentials_are_omitted_from_settings_repr(self):
        settings = Settings(database_url=URL, database_ssl_pem_b64="PRIVATE_TEST_VALUE",
                            admin_api_key="PRIVATE_ADMIN_VALUE", openai_api_key="PRIVATE_AI_VALUE")
        for value in [URL, "PRIVATE_TEST_VALUE", "PRIVATE_ADMIN_VALUE", "PRIVATE_AI_VALUE"]:
            self.assertNotIn(value, repr(settings))

    def test_reads_ssl_variables_from_environment(self):
        values = {"DATABASE_URL": URL, "DATABASE_SSL_CA_B64": "ca", "DATABASE_SSL_CERT_B64": "cert",
                  "DATABASE_SSL_KEY_B64": "key", "DATABASE_SSL_MODE": "verify-full"}
        with patch.dict(os.environ, values, clear=True), patch("atendeai.config.load_dotenv"):
            settings = Settings.from_env()
        self.assertEqual(settings.database_ssl_ca_b64, "ca")
        self.assertEqual(settings.database_ssl_cert_b64, "cert")
        self.assertEqual(settings.database_ssl_key_b64, "key")
        self.assertEqual(settings.database_ssl_mode, "verify-full")

    def test_invalid_base64_and_pem_do_not_echo_credentials(self):
        for value in ["PRIVATE_SECRET!", base64.b64encode(b"PRIVATE_SECRET_NOT_PEM").decode()]:
            with self.subTest(value=value), self.assertRaises(ValueError) as failure:
                settings = Settings(database_url=URL, database_ssl_pem_b64=value)
                DatabaseSSL(settings, settings.validated())
            self.assertNotIn(value, str(failure.exception))
            self.assertNotIn("PRIVATE_SECRET", str(failure.exception))

    def test_without_certificates_preserves_existing_connection_settings(self):
        settings = Settings(database_url=URL + "?sslmode=require")
        with DatabaseSSL(settings, settings.validated()) as files:
            self.assertEqual(files.connect_args, {})

    def test_ssl_parameters_reach_postgresql_driver_with_timeout(self):
        ssl_args = {"sslmode": "verify-ca", "sslrootcert": "/private/ca.pem",
                    "sslcert": "/private/cert.pem", "sslkey": "/private/key.pem"}
        with patch("atendeai.models.create_engine") as factory:
            factory.return_value = MagicMock()
            build_database(Settings(database_url=URL).validated(), connect_args=ssl_args)
        self.assertEqual(factory.call_args.kwargs["connect_args"], {"connect_timeout": 10, **ssl_args})


@unittest.skipUnless(shutil.which("openssl"), "Testes de PEM exigem o executável openssl")
class CertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = TemporaryDirectory(prefix="atendeai-test-ssl-")
        cls.root = Path(cls.directory.name)
        # Certificados fictícios e efêmeros, gerados somente durante o teste.
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=AtendeAI Test Only", "-keyout", str(cls.root / "key.pem"),
                        "-out", str(cls.root / "cert.pem")], check=True, capture_output=True)
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                        "-out", str(cls.root / "other.key")], check=True, capture_output=True)
        cls.cert = (cls.root / "cert.pem").read_bytes()
        cls.key = (cls.root / "key.pem").read_bytes()
        cls.bundle = cls.cert + cls.key
        (cls.root / "bundle.pem").write_bytes(cls.bundle)
        encode = lambda data: base64.b64encode(data).decode("ascii")
        cls.settings = Settings(database_url=URL, database_ssl_ca_b64=encode(cls.cert),
                                database_ssl_cert_b64=encode(cls.cert), database_ssl_key_b64=encode(cls.key))
        cls.combined = Settings(database_url=URL, database_ssl_pem_b64=encode(cls.bundle))

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_split_certificates_validate_permissions_and_cleanup(self):
        with DatabaseSSL(self.settings, self.settings.validated()) as files:
            self.assertEqual(files.connect_args["sslmode"], "verify-ca")
            paths = [Path(files.connect_args[name]) for name in ["sslrootcert", "sslcert", "sslkey"]]
            self.assertEqual(paths[0].read_bytes(), self.cert)
            self.assertEqual(paths[1].read_bytes(), self.cert)
            self.assertEqual(paths[2].read_bytes(), self.key)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(paths[0].parent.stat().st_mode), 0o700)
                for path in paths:
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertTrue(all(not path.exists() for path in paths))

    def test_combined_squarecloud_pem_maps_to_all_three_ssl_fields(self):
        with DatabaseSSL(self.combined, self.combined.validated()) as files:
            self.assertEqual(files.connect_args["sslrootcert"], files.connect_args["sslcert"])
            self.assertEqual(files.connect_args["sslcert"], files.connect_args["sslkey"])
            path = Path(files.connect_args["sslkey"])
            self.assertEqual(path.read_bytes(), self.bundle)
        self.assertFalse(path.exists())

    def test_mismatched_key_is_rejected_before_connection(self):
        wrong_key = base64.b64encode((self.root / "other.key").read_bytes()).decode("ascii")
        settings = replace(self.settings, database_ssl_key_b64=wrong_key)
        with self.assertRaisesRegex(ValueError, "Certificado/chave"):
            DatabaseSSL(settings, settings.validated())

    def test_server_name_verification_is_preserved_and_can_be_requested(self):
        for changes in [{"database_url": URL + "?sslmode=verify-full"}, {"database_ssl_mode": "verify-full"}]:
            settings = replace(self.settings, **changes)
            with DatabaseSSL(settings, settings.validated()) as files:
                self.assertEqual(files.connect_args["sslmode"], "verify-full")
        settings = replace(self.settings, database_url=URL + "?sslmode=disable")
        with DatabaseSSL(settings, settings.validated()) as files:
            self.assertEqual(files.connect_args["sslmode"], "verify-ca")

    def test_startup_failure_disposes_engine_and_removes_private_files(self):
        instances = []

        def prepare(*args):
            instance = DatabaseSSL(*args)
            instances.append(instance)
            return instance

        engine = MagicMock()
        with patch("atendeai.api.DatabaseSSL", side_effect=prepare), \
                patch("atendeai.api.build_database", return_value=(engine, MagicMock())), \
                patch("atendeai.api.Base.metadata.create_all", side_effect=SQLAlchemyError("test database unavailable")):
            app = create_app(self.settings)
            path = Path(instances[0].connect_args["sslkey"])
            self.assertTrue(path.exists())
            with self.assertRaises(SQLAlchemyError), TestClient(app):
                pass
        engine.dispose.assert_called_once()
        self.assertFalse(path.exists())

    def test_converter_writes_private_import_file_and_does_not_print_key(self):
        script = Path(__file__).resolve().parents[1] / "certificados_env.py"
        with TemporaryDirectory() as output_directory:
            output = Path(output_directory) / ".env.certificados.txt"
            command = [sys.executable, str(script), "--pem", str(self.root / "bundle.pem"), "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("BEGIN PRIVATE KEY", result.stdout + result.stderr)
            self.assertNotIn(self.combined.database_ssl_pem_b64, result.stdout + result.stderr)
            lines = dict(line.split("=", 1) for line in output.read_text().splitlines())
            self.assertEqual(lines["DATABASE_SSL_MODE"], "verify-ca")
            self.assertEqual(base64.b64decode(lines["DATABASE_SSL_PEM_B64"]), self.bundle)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            duplicate = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(duplicate.returncode, 0)


if __name__ == "__main__":
    unittest.main()
