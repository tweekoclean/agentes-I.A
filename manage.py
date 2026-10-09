"""Comandos locais: python manage.py --help."""
import argparse
import json
from pathlib import Path
import secrets

from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from atendeai.config import Settings
from atendeai.database_ssl import DatabaseSSL
from atendeai.models import Base, build_database


def main():
    parser = argparse.ArgumentParser(description="Configuração da API AtendeAI")
    parser.add_argument("comando", choices=["gerar-chave", "iniciar-banco", "verificar-banco", "gerar-sql"])
    args = parser.parse_args()
    if args.comando == "gerar-chave":
        print(secrets.token_urlsafe(32))
        return
    if args.comando == "gerar-sql":
        dialect = postgresql.dialect()
        statements = [str(CreateTable(table).compile(dialect=dialect)) + ";" for table in Base.metadata.sorted_tables]
        statements += [str(CreateIndex(index).compile(dialect=dialect)) + ";" for table in Base.metadata.sorted_tables for index in table.indexes]
        path = Path("schema-postgresql.sql")
        content = "-- Nelvo Company 0.8.0: criar em um banco vazio, uma única vez.\n" + "\n\n".join(statements)
        path.write_text("\n".join(line.rstrip() for line in content.splitlines()).rstrip() + "\n", encoding="utf-8")
        print("schema-postgresql.sql gerado.")
        return
    settings = Settings.from_env()
    database_url = settings.validated()
    with DatabaseSSL(settings, database_url) as ssl_files:
        engine, _ = build_database(database_url, connect_args=ssl_files.connect_args)
        try:
            if args.comando == "iniciar-banco":
                Base.metadata.create_all(engine)
                print("Tabelas criadas; registros existentes foram preservados.")
            else:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                print("Conexão com o banco: OK.")
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
