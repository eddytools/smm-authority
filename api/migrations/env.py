from alembic import context

from app import models  # noqa: F401  (registers every table on Base.metadata)
from app.config import get_settings
from app.db import Base, make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Tests and tooling can hand an engine/URL in through the config; otherwise use the app's own setting.
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = make_engine(_url())
    with engine.connect() as conn:
        _run(conn)
    engine.dispose()


def _run(connection) -> None:
    # render_as_batch lets SQLite perform ALTERs that need a table rebuild; it is harmless elsewhere.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
