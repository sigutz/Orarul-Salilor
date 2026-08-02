"""Alembic environment.

Ia URL-ul si metadatele din aplicatie, nu din alembic.ini, ca sa existe o singura
sursa de adevar (`orar.db.session.cale_db` respecta si variabila ORAR_DB).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

from orar.db.models import Base
from orar.db.session import get_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(get_engine().url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = get_engine()
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite nu stie ALTER TABLE complet; batch mode recreeaza tabela.
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
