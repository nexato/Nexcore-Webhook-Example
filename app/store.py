"""Local persistent state, backed by stdlib ``sqlite3`` (no third-party DB).

Two responsibilities:

1. **Idempotency** — remember which webhook event IDs have already been
   processed, so a redelivery (Nexcore retries up to 4×) doesn't download the
   same files twice.
2. **Subscription state** — the app manages its own subscription and must keep
   the plaintext ``secret`` locally: the server only stores ``sha256hex(secret)``
   and cannot return it, yet we need it to verify incoming signatures.

The store opens a short-lived connection per operation, which keeps it safe to
call from FastAPI background tasks running in the threadpool.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SubscriptionState:
    """Locally persisted subscription record."""

    external_id: str
    subscription_id: str | None
    secret: str | None


class Store:
    """SQLite-backed state store. Pass an explicit ``db_path`` (file or ``:memory:``)."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        # Ensure the parent directory exists for file-based paths.
        if self._db_path not in (":memory:", "") and (parent := Path(self._db_path).parent):
            parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS processed_events (
                    event_id     TEXT PRIMARY KEY,
                    processed_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS subscription_state (
                    external_id     TEXT PRIMARY KEY,
                    subscription_id TEXT,
                    secret          TEXT,
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )

    # --- Idempotency --------------------------------------------------------

    def is_event_processed(self, event_id: str) -> bool:
        """Return ``True`` if ``event_id`` has already been recorded."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,)
            ).fetchone()
        return row is not None

    def mark_event_processed(self, event_id: str) -> bool:
        """Atomically claim ``event_id``.

        Returns ``True`` if this call inserted the row (caller should process the
        event), ``False`` if it was already present (a duplicate to skip). The
        atomic INSERT makes "process exactly once" race-free across threads.
        """
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO processed_events (event_id) VALUES (?)", (event_id,)
            )
        return cur.rowcount == 1

    def unmark_event_processed(self, event_id: str) -> None:
        """Release a previously claimed event id (e.g. after a failed download)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM processed_events WHERE event_id = ?", (event_id,))

    # --- Subscription state -------------------------------------------------

    def save_subscription(
        self,
        external_id: str,
        subscription_id: str | None = None,
        secret: str | None = None,
    ) -> None:
        """Upsert the subscription record for ``external_id``."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO subscription_state (external_id, subscription_id, secret, updated_at)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(external_id) DO UPDATE SET
                    subscription_id = excluded.subscription_id,
                    secret          = excluded.secret,
                    updated_at      = excluded.updated_at
                """,
                (external_id, subscription_id, secret),
            )

    def get_subscription(self, external_id: str) -> SubscriptionState | None:
        """Return the stored subscription for ``external_id`` (or ``None``)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT external_id, subscription_id, secret FROM subscription_state "
                "WHERE external_id = ?",
                (external_id,),
            ).fetchone()
        if row is None:
            return None
        return SubscriptionState(
            external_id=row["external_id"],
            subscription_id=row["subscription_id"],
            secret=row["secret"],
        )

    def delete_subscription(self, external_id: str) -> None:
        """Remove the locally stored subscription record."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM subscription_state WHERE external_id = ?", (external_id,)
            )
