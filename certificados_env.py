"""Converte certificados locais para um arquivo privado de variáveis da Square Cloud."""
import argparse
import base64
import os
from pathlib import Path

from atendeai.config import Settings
from atendeai.database_ssl import DatabaseSSL


def main():
    parser = argparse.ArgumentParser(description="Preparar certificados PostgreSQL para variáveis de ambiente")
    parser.add_argument("--pem", type=Path, help="certificate.pem combinado da Square Cloud")
    parser.add_argument("--ca", type=Path, help="Certificado da autoridade certificadora")
    parser.add_argument("--cert", type=Path, help="Certificado do cliente")
    parser.add_argument("--key", type=Path, help="Chave privada do cliente")
    parser.add_argument("--output", type=Path, default=Path(".env.certificados.txt"))
    args = parser.parse_args()
    separate = [args.ca, args.cert, args.key]
    if args.pem and any(separate):
        parser.error("Use --pem ou --ca/--cert/--key, sem misturar as opções.")
    if not args.pem and not all(separate):
        parser.error("Informe --pem ou as três opções --ca, --cert e --key.")
    paths = {"DATABASE_SSL_PEM_B64": args.pem} if args.pem else {
        "DATABASE_SSL_CA_B64": args.ca, "DATABASE_SSL_CERT_B64": args.cert,
        "DATABASE_SSL_KEY_B64": args.key,
    }
    # Não permite gerar segredos em um nome que ficaria fora do .gitignore.
    if not args.output.name.startswith(".env.") or args.output.name == ".env.example":
        parser.error("O arquivo de saída deve começar com .env. e não pode ser .env.example.")
    try:
        values = {name: base64.b64encode(path.read_bytes()).decode("ascii") for name, path in paths.items()}
        settings = Settings(database_url="postgresql://user:placeholder@localhost/test",
                            **{name.lower(): value for name, value in values.items()})
        with DatabaseSSL(settings, settings.validated()):
            pass
        content = "DATABASE_SSL_MODE=verify-ca\n" + "".join(f"{name}={value}\n" for name, value in values.items())
        # Recusa sobrescrever um arquivo existente; não imprime seu conteúdo.
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Não foi possível preparar os certificados: {error}\n")
    print(f"Arquivo criado: {args.output}. Importe na Square Cloud junto com DATABASE_URL.")
    print("O arquivo contém a chave privada em Base64. Guarde nas variáveis da hospedagem.")


if __name__ == "__main__":
    main()
