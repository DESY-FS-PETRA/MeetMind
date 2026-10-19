from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.database.base import Base


DEFAULT_DATABASE_PATH = Path("data/meeting_ai.db")


def resolve_database_url(database_url: str | None = None) -> str:
    url = database_url or os.getenv("DATABASE_URL")
    if url:
        return url

    DEFAULT_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"


class Database:
    """Owns the SQLAlchemy engine and creates short-lived Sessions."""

    def __init__(self, database_url: str | None = None) -> None:
        self.url = resolve_database_url(database_url)
        connect_args = {"check_same_thread": False} if self.url.startswith("sqlite") else {}
        engine_kwargs = {
            "connect_args": connect_args,
            "pool_pre_ping": True,
        }
        # File-backed SQLite databases can remain locked on Windows when the
        # default QueuePool keeps an idle connection open.  MeetMind uses
        # short-lived ORM sessions, so NullPool is a better fit for SQLite:
        # each connection is closed as soon as its session/transaction ends.
        # This also makes temporary databases reliably removable in tests.
        if self.url.startswith("sqlite"):
            engine_kwargs["poolclass"] = NullPool

        self.engine: Engine = create_engine(
            self.url,
            **engine_kwargs,
        )

        if self.url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)

        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_schema(self) -> None:
        # Import models before create_all so all tables are registered.
        from app.database import models  # noqa: F401

        Base.metadata.create_all(self.engine)
        self._apply_compatible_schema_upgrades()

    def _apply_compatible_schema_upgrades(self) -> None:
        """Add nullable JSON extras without requiring a destructive migration.

        Existing Phase 5.x SQLite databases remain valid. PostgreSQL also
        accepts the JSON column declaration used here.
        """
        inspector = inspect(self.engine)
        if "meeting_summary_extras" not in inspector.get_table_names():
            return
        columns = {item["name"] for item in inspector.get_columns("meeting_summary_extras")}
        if "discussion_questions" in columns:
            return
        dialect = self.engine.dialect.name
        json_type = "JSONB" if dialect == "postgresql" else "JSON"
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE meeting_summary_extras "
                    f"ADD COLUMN discussion_questions {json_type}"
                )
            )

    def session(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
