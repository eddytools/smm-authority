from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from app import models  # noqa: F401
from app.config import Settings
from app.db import Base, SchemaOutOfDate, ensure_migrated, make_engine, migration_head, prepare_schema

API = Path(__file__).resolve().parent.parent


def alembic_config(url: str) -> Config:
    cfg = Config(str(API / "alembic.ini"))
    cfg.set_main_option("script_location", str(API / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'm.db'}"


def test_migrations_build_exactly_the_schema_the_models_describe(db_url):
    command.upgrade(alembic_config(db_url), "head")
    engine = make_engine(db_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == [], f"models changed without a migration: {diff}"


def test_downgrade_to_base_removes_everything(db_url):
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert set(inspect(make_engine(db_url)).get_table_names()) <= {"alembic_version"}


def test_production_refuses_an_unmigrated_database_and_accepts_a_migrated_one(db_url):
    engine = make_engine(db_url)
    with pytest.raises(SchemaOutOfDate, match="alembic upgrade head"):
        ensure_migrated(engine)
    command.upgrade(alembic_config(db_url), "head")
    ensure_migrated(engine)
    assert migration_head()


def test_production_never_creates_tables_implicitly(db_url):
    engine = make_engine(db_url)
    settings = Settings(env="production", database_url=db_url, secret_key="x" * 40)
    with pytest.raises(SchemaOutOfDate):
        prepare_schema(engine, settings)
    assert inspect(engine).get_table_names() == []
