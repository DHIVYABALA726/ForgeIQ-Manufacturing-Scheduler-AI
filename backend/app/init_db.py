from __future__ import annotations
from pathlib import Path
from alembic import command
from alembic.config import Config
from .database import engine


def initialize_schema() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    # Pass the same normalized/TLS-configured connection used by FastAPI so
    # managed MySQL and local/production SQLAlchemy URLs behave identically.
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


if __name__ == "__main__":
    initialize_schema()
    print("ForgeIQ database schema is current (Alembic head).")
