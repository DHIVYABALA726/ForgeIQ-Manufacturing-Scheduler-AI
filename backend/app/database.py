from __future__ import annotations

import os
import ssl
from collections.abc import Generator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


class Base(DeclarativeBase):
    pass


def _normalize_database_url(raw: str | None = None) -> tuple[URL, dict]:
    raw = (raw if raw is not None else os.getenv("DATABASE_URL", "")).strip()
    if not raw:
        local_file = Path(__file__).resolve().parents[1] / "data" / "forgeiq.db"
        local_file.parent.mkdir(parents=True, exist_ok=True)
        return URL.create("sqlite", database=str(local_file)), {}

    if raw.startswith("mysql://"):
        raw = raw.replace("mysql://", "mysql+pymysql://", 1)
    elif raw.startswith("postgres://"):
        raw = raw.replace("postgres://", "postgresql+psycopg://", 1)
    elif raw.startswith("postgresql://") and "+" not in raw.split(":", 1)[0]:
        raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)

    url = make_url(raw)
    connect_args: dict = {}
    if url.drivername == "mysql+pymysql":
        raw_tls = url.query.get("ssl")
        if isinstance(raw_tls, tuple):
            raw_tls = raw_tls[-1]
        tls_value = str(raw_tls or "").strip()
        if tls_value.lower() in {"0", "false", "no", "off", "disable", "disabled", "none"}:
            raise ValueError("ForgeIQ requires TLS for external MySQL connections; remove ssl=false or configure a trusted TLS connection.")
        cafile = tls_value if tls_value and Path(tls_value).is_file() else None
        # PyMySQL needs a context, not the string-valued DSN query parameter.
        # Default trust roots plus hostname verification fail closed if the
        # server certificate is untrusted or does not match its database host.
        connect_args["ssl"] = ssl.create_default_context(cafile=cafile)
        if "ssl" in url.query:
            url = url.difference_update_query(["ssl"])
    elif url.drivername.startswith("postgresql"):
        raw_mode = url.query.get("sslmode")
        if isinstance(raw_mode, tuple):
            raw_mode = raw_mode[-1]
        if str(raw_mode or "").lower() != "verify-full":
            # libpq validates both the CA chain and database hostname. A caller
            # may additionally provide sslrootcert in DATABASE_URL when needed.
            url = url.update_query_dict({"sslmode": "verify-full"})

    return url, ({"connect_args": connect_args} if connect_args else {})


DATABASE_URL, _driver_options = _normalize_database_url()
_is_sqlite = DATABASE_URL.drivername.startswith("sqlite")
_engine_options: dict = {"pool_pre_ping": True, **_driver_options}
if _is_sqlite:
    _engine_options["connect_args"] = {**_engine_options.get("connect_args", {}), "check_same_thread": False}
engine = create_engine(DATABASE_URL, **_engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
