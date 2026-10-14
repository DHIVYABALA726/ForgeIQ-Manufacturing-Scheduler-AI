from __future__ import annotations
from logging.config import fileConfig
from alembic import context
from sqlalchemy.engine import Connection
from app.database import engine, Base
from app import models  # noqa: F401 — registers all migration metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    with engine.connect() as migration_connection:
        _run(migration_connection)
