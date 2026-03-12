"""Operation journal — tracks every action for rollback and audit."""

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path

from src.core.logger import get_logger

log = get_logger("rollback.journal")


@dataclass
class JournalEntry:
    id: int = 0
    timestamp: float = 0.0
    action: str = ""
    target: str = ""
    details: str = ""
    risk_level: str = "green"
    backup_path: str = ""
    rollback_cmd: str = ""
    status: str = "pending"  # pending | completed | rolled_back | failed
    session_id: str = ""


class Journal:
    """SQLite-backed operation journal."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT DEFAULT '',
                    details TEXT DEFAULT '',
                    risk_level TEXT DEFAULT 'green',
                    backup_path TEXT DEFAULT '',
                    rollback_cmd TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    session_id TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_journal_session ON journal(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_journal_status ON journal(status)
            """)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record(
        self,
        action: str,
        target: str = "",
        details: str = "",
        risk_level: str = "green",
        backup_path: str = "",
        rollback_cmd: str = "",
        session_id: str = "",
    ) -> int:
        """Record a new operation in the journal. Returns the entry ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO journal
                   (timestamp, action, target, details, risk_level, backup_path, rollback_cmd, status, session_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'completed', ?)""",
                (time.time(), action, target, details, risk_level, backup_path, rollback_cmd, session_id),
            )
            entry_id = cursor.lastrowid
            log.info("Journal entry #%d: %s on %s", entry_id, action, target)
            return entry_id

    def update_status(self, entry_id: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE journal SET status = ? WHERE id = ?", (status, entry_id))

    def get_entry(self, entry_id: int) -> JournalEntry | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM journal WHERE id = ?", (entry_id,)).fetchone()
            if row:
                return self._row_to_entry(row)
            return None

    def get_recent(self, limit: int = 50) -> list[JournalEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM journal ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row_to_entry(r) for r in rows]

    def get_session_entries(self, session_id: str) -> list[JournalEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM journal WHERE session_id = ? ORDER BY id DESC",
                (session_id,),
            ).fetchall()
            return [self._row_to_entry(r) for r in rows]

    def get_rollbackable(self) -> list[JournalEntry]:
        """Get entries that can be rolled back (have backup_path and status=completed)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM journal WHERE status = 'completed' AND backup_path != '' ORDER BY id DESC"
            ).fetchall()
            return [self._row_to_entry(r) for r in rows]

    def get_entry_by_backup_path(self, backup_path: str) -> JournalEntry | None:
        """Find the most recent completed entry with the given backup_path."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM journal WHERE backup_path = ? AND status = 'completed' "
                "ORDER BY id DESC LIMIT 1",
                (backup_path,),
            ).fetchone()
            return self._row_to_entry(row) if row else None

    @staticmethod
    def _row_to_entry(row) -> JournalEntry:
        return JournalEntry(
            id=row["id"],
            timestamp=row["timestamp"],
            action=row["action"],
            target=row["target"],
            details=row["details"],
            risk_level=row["risk_level"],
            backup_path=row["backup_path"],
            rollback_cmd=row["rollback_cmd"],
            status=row["status"],
            session_id=row["session_id"],
        )
