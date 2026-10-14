from __future__ import annotations
import ssl
from pathlib import Path
import pytest
from app.database import _normalize_database_url


def test_mysql_tls_dsn_string_becomes_verified_pymysql_ssl_context():
    url, options = _normalize_database_url("mysql://forgeiq@db.example.test/forgeiq?ssl=true")
    assert url.drivername == "mysql+pymysql"
    assert "ssl" not in url.query
    context = options["connect_args"]["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_mysql_tls_is_enabled_even_when_the_dsn_omits_an_ssl_parameter():
    _, options = _normalize_database_url("mysql://forgeiq@db.example.test/forgeiq")
    context = options["connect_args"]["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_plaintext_mysql_is_rejected():
    with pytest.raises(ValueError, match="requires TLS"):
        _normalize_database_url("mysql://forgeiq@db.example.test/forgeiq?ssl=false")


def test_postgres_defaults_to_hostname_and_certificate_verification():
    url, options = _normalize_database_url("postgresql://forgeiq@db.example.test/forgeiq")
    assert url.drivername == "postgresql+psycopg"
    assert url.query["sslmode"] == "verify-full"
    assert options == {}


def test_postgres_insecure_sslmode_is_upgraded_to_verify_full():
    url, _ = _normalize_database_url("postgres://forgeiq@db.example.test/forgeiq?sslmode=prefer")
    assert url.query["sslmode"] == "verify-full"


def test_local_default_sqlite_file_matches_documented_persistent_data_directory():
    url, options = _normalize_database_url("")
    assert url.drivername == "sqlite"
    assert url.database is not None
    assert Path(url.database).as_posix().endswith("/backend/data/forgeiq.db")
    assert options == {}
