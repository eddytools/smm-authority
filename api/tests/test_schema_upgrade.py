import pytest
from sqlalchemy import Boolean, Column, Integer, String, text
from sqlalchemy.orm import sessionmaker

from app.db import Base, SchemaOutOfDate, _literal_default, init_schema, make_engine, missing_columns
from app.framework import SlotStatus
from app.models import PlanSlot, User, Venture
from datetime import datetime, timezone

NEW_SLOT_COLUMNS = ["published_at", "external_id", "external_url", "publish_attempts", "next_attempt_at", "publish_error", "claimed_at"]


def old_database(tmp_path):
    """A database as an earlier version of the app left it: populated, with the publishing columns missing."""
    engine = make_engine(f"sqlite:///{tmp_path}/old.db")
    init_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user = User(email="a@example.com", name="A", password_hash="x")
        db.add(user)
        db.flush()
        v = Venture(owner_id=user.id, name="Acme")
        db.add(v)
        db.flush()
        db.add(PlanSlot(venture_id=v.id, scheduled_at=datetime(2026, 11, 2, 8, 30, tzinfo=timezone.utc), platform="linkedin", post_type="story", stage="mofu",
                        topic="Keep me", draft="My draft", status=SlotStatus.drafted))
        db.commit()
    with engine.begin() as conn:
        for col in NEW_SLOT_COLUMNS:
            conn.execute(text(f"ALTER TABLE plan_slots DROP COLUMN {col}"))
    return engine, factory


def test_old_sqlite_database_is_upgraded_in_place_and_keeps_its_data(tmp_path):
    engine, factory = old_database(tmp_path)
    assert {c.name for _, c in missing_columns(engine)} == set(NEW_SLOT_COLUMNS)
    changes = init_schema(engine)
    assert sorted(changes) == sorted(f"added plan_slots.{c}" for c in NEW_SLOT_COLUMNS)
    assert missing_columns(engine) == []
    with factory() as db:
        slot = db.query(PlanSlot).one()
        assert (slot.topic, slot.draft, slot.status) == ("Keep me", "My draft", SlotStatus.drafted)  # nothing lost
        assert slot.publish_attempts == 0 and slot.publish_error is None and slot.external_url is None  # NOT NULL column got its default
        slot.publish_attempts += 1  # and the new columns are usable
        db.commit()
    assert init_schema(engine) == []  # idempotent


def test_other_databases_are_never_altered_and_stop_with_a_clear_message(tmp_path):
    engine, _ = old_database(tmp_path)
    with pytest.raises(SchemaOutOfDate) as e:
        init_schema(engine, allow_alter=False)  # what happens on Postgres
    assert "plan_slots.published_at" in str(e.value) and "migration" in str(e.value)
    assert {c.name for _, c in missing_columns(engine)} == set(NEW_SLOT_COLUMNS)  # untouched


def test_default_literals_for_not_null_columns():
    assert _literal_default(Column("a", Integer, nullable=False)) is None  # no default: can't be added automatically
    assert _literal_default(Column("b", Boolean, default=False)) == "0" and _literal_default(Column("b", Boolean, default=True)) == "1"
    assert _literal_default(Column("c", Integer, default=7)) == "7"
    assert _literal_default(Column("d", String, default="it's")) == "'it''s'"
    assert _literal_default(Column("e", Integer, default=lambda: 1)) is None  # callable defaults are not literals


def test_fresh_database_needs_no_changes(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/fresh.db")
    assert init_schema(engine) == [] and init_schema(engine) == []


def test_init_schema_registers_the_tables_itself():
    """Called first in a brand-new process, before anything imported the models, it must still create the schema."""
    import subprocess
    import sys

    code = "from sqlalchemy import inspect\nfrom app.db import make_engine, init_schema\ne = make_engine('sqlite://')\ninit_schema(e)\nprint(len(inspect(e).get_table_names()))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=".")
    assert out.returncode == 0, out.stderr
    assert int(out.stdout.strip()) == len(Base.metadata.tables) > 0  # every table the app defines, not a hard-coded number
