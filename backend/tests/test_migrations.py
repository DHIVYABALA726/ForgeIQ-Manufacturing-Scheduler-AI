from __future__ import annotations

from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool


def _config(project_root: Path, connection) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def test_fresh_schema_migration_is_recorded_and_repeatable():
    project_root = Path(__file__).resolve().parents[2]
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        for _ in range(2):
            with engine.connect() as connection:
                command.upgrade(_config(project_root, connection), "head")
        inspector = inspect(engine)
        names = set(inspector.get_table_names())
        assert {"alembic_version", "dataset_state", "jobs", "machines", "operations", "schedule_runs", "algorithm_results", "scheduled_operations", "recommendations", "disruption_events"}.issubset(names)
        columns = {table: {column["name"] for column in inspector.get_columns(table)} for table in ("jobs", "machines", "operations")}
        assert {"component_type", "status"}.issubset(columns["jobs"])
        assert {"processing_capabilities", "maintenance_schedule"}.issubset(columns["machines"])
        assert "required_capability" in columns["operations"]
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0003_automotive_ai_search"
    finally:
        engine.dispose()


def test_automotive_revision_preserves_and_backfills_preexisting_generic_rows():
    project_root = Path(__file__).resolve().parents[2]
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            connection.exec_driver_sql("INSERT INTO alembic_version(version_num) VALUES ('0002_dynamic_rescheduling')")
            connection.exec_driver_sql("CREATE TABLE jobs (id VARCHAR(80) PRIMARY KEY, name VARCHAR(160) NOT NULL, product_name VARCHAR(160) NOT NULL, quantity INTEGER NOT NULL, priority VARCHAR(20) NOT NULL, release_at DATETIME NOT NULL, due_at DATETIME NOT NULL, notes TEXT, is_sample BOOLEAN NOT NULL)")
            connection.exec_driver_sql("CREATE TABLE machines (id VARCHAR(80) PRIMARY KEY, name VARCHAR(160) NOT NULL, machine_type VARCHAR(120) NOT NULL, available_from DATETIME NOT NULL, available_until DATETIME, is_available BOOLEAN NOT NULL, setup_time_minutes INTEGER NOT NULL, is_sample BOOLEAN NOT NULL)")
            connection.exec_driver_sql("CREATE TABLE operations (id VARCHAR(80) PRIMARY KEY, job_id VARCHAR(80) NOT NULL, name VARCHAR(160) NOT NULL, sequence INTEGER NOT NULL, eligible_machine_ids JSON NOT NULL, processing_time_minutes INTEGER NOT NULL, setup_time_minutes INTEGER NOT NULL, predecessor_id VARCHAR(80), is_sample BOOLEAN NOT NULL)")
            connection.exec_driver_sql("INSERT INTO jobs VALUES ('OLD-J1','Legacy order','Legacy product',7,'Medium','2030-01-01 08:00:00','2030-01-01 17:00:00',NULL,0)")
            connection.exec_driver_sql("INSERT INTO machines VALUES ('OLD-M1','Legacy machine','CNC mill','2030-01-01 08:00:00',NULL,1,0,0)")
            connection.exec_driver_sql("INSERT INTO operations VALUES ('OLD-O1','OLD-J1','Legacy cut',1,'[\"OLD-M1\"]',30,0,NULL,0)")
        with engine.connect() as connection:
            command.upgrade(_config(project_root, connection), "head")
        with engine.connect() as connection:
            job = connection.execute(text("SELECT id, component_type, status FROM jobs WHERE id='OLD-J1'")).one()
            machine = connection.execute(text("SELECT id, processing_capabilities, maintenance_schedule FROM machines WHERE id='OLD-M1'")).one()
            operation = connection.execute(text("SELECT id, required_capability FROM operations WHERE id='OLD-O1'")).one()
            assert tuple(job) == ("OLD-J1", "other", "queued")
            assert tuple(machine) == ("OLD-M1", "[]", "[]")
            assert tuple(operation) == ("OLD-O1", None)
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0003_automotive_ai_search"
    finally:
        engine.dispose()
