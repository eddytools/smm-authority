import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)

    kwargs: dict = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


log = logging.getLogger("smm.db")


class SchemaOutOfDate(RuntimeError):
    pass


def _literal_default(column) -> str | None:
    """A SQL literal for a NOT NULL column's Python-side default, or None when there isn't a simple scalar one."""
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def missing_columns(engine: Engine) -> list[tuple[str, object]]:
    existing = {t: {c["name"] for c in inspect(engine).get_columns(t)} for t in inspect(engine).get_table_names()}
    return [(table.name, col) for table in Base.metadata.sorted_tables if table.name in existing for col in table.columns if col.name not in existing[table.name]]


def init_schema(engine: Engine, allow_alter: bool | None = None) -> list[str]:
    """Create missing tables, then bring existing tables up to date.

    Stand-in for real migrations (Alembic) while the project is pre-release. On SQLite (development) missing columns are
    added in place, keeping data. On any other database nothing is altered: startup stops with a clear list of what is
    missing instead of failing later with confusing errors. Returns a description of each change made."""
    from app import models  # noqa: F401  (importing registers every table on Base.metadata, whoever calls this first)

    Base.metadata.create_all(engine)
    missing = missing_columns(engine)
    if not missing:
        return []
    if allow_alter is None:
        allow_alter = engine.dialect.name == "sqlite"
    names = ", ".join(f"{t}.{c.name}" for t, c in missing)
    if not allow_alter:
        raise SchemaOutOfDate(f"The database schema is out of date (missing columns: {names}). Apply a migration, then restart.")
    changes = []
    with engine.begin() as conn:
        for table, col in missing:
            ddl = f'ALTER TABLE "{table}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
            if not col.nullable:
                default = _literal_default(col)
                if default is None:
                    raise SchemaOutOfDate(f"Cannot add NOT NULL column {table}.{col.name} automatically (no simple default). Migrate the database by hand.")
                ddl += f" NOT NULL DEFAULT {default}"
            conn.execute(text(ddl))
            changes.append(f"added {table}.{col.name}")
    log.warning("Upgraded the database schema in place: %s", "; ".join(changes))
    return changes
