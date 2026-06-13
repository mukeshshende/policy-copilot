"""
governance.py — SQLite governance registry for Policy Copilot
AIpportunity Pvt. Ltd.

Logs every agent run to a local SQLite database for audit, observability,
and ADLC governance demonstration.

Schema (single table: query_log)
─────────────────────────────────
  run_id        TEXT  PRIMARY KEY   — UUID from AgentState.run_id
  timestamp     TEXT  NOT NULL      — ISO-8601 UTC
  user_role     TEXT  NOT NULL      — employee | manager | HR | IT_admin | Leadership
  query         TEXT  NOT NULL      — raw user question
  collections   TEXT  NOT NULL      — JSON list of collections searched
  retrieved     INT   NOT NULL      — total chunks retrieved
  graded        INT   NOT NULL      — chunks that passed relevance grading
  sources       TEXT  NOT NULL      — JSON list of source file names cited
  answer_len    INT   NOT NULL      — character count of the generated answer
  outcome       TEXT  NOT NULL      — "answered" | "no_results" | "error"
  error_msg     TEXT                — populated only when outcome="error"

Usage
──────
    from src.governance.governance import GovernanceDB

    db = GovernanceDB()            # or GovernanceDB("path/to/governance.db")
    db.log_run(final_state)        # call after every graph.invoke()
    rows = db.recent_runs(n=10)    # list last 10 runs
    db.close()
"""

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.environ.get("GOVERNANCE_DB", "./data/governance.db")

# DDL — creates the table if it does not already exist
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS query_log (
    run_id       TEXT PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    user_role    TEXT NOT NULL,
    query        TEXT NOT NULL,
    collections  TEXT NOT NULL,
    retrieved    INTEGER NOT NULL DEFAULT 0,
    graded       INTEGER NOT NULL DEFAULT 0,
    sources      TEXT NOT NULL DEFAULT '[]',
    answer_len   INTEGER NOT NULL DEFAULT 0,
    outcome      TEXT NOT NULL DEFAULT 'answered',
    error_msg    TEXT
);
"""


class GovernanceDB:
    """
    Thin wrapper around a SQLite connection for Policy Copilot audit logging.

    Thread safety: SQLite in check_same_thread=False mode is safe for single-
    process, multi-threaded use (Gradio runs in threads).  For multi-process
    deployments use a proper database.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _DEFAULT_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")  # concurrent reads
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()
        logger.info(f"[GovernanceDB] opened: {self.db_path}")

    # ── Write ──────────────────────────────────────────────────────────────────

    def log_run(self, state: dict[str, Any]) -> None:
        """
        Persist a completed AgentState to the query_log table.

        Safe to call even if the run errored — outcome is derived from
        AgentState.error and AgentState.graded_docs.
        """
        error_msg = state.get("error", "") or ""

        if error_msg:
            outcome = "error"
        elif not (state.get("graded_docs") or []):
            outcome = "no_results"
        else:
            outcome = "answered"

        row = {
            "run_id":      state.get("run_id", ""),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "user_role":   state.get("user_role", "unknown"),
            "query":       state.get("query", ""),
            "collections": json.dumps(state.get("collections") or []),
            "retrieved":   len(state.get("retrieved_docs") or []),
            "graded":      len(state.get("graded_docs") or []),
            "sources":     json.dumps(state.get("sources") or []),
            "answer_len":  len(state.get("answer") or ""),
            "outcome":     outcome,
            "error_msg":   error_msg or None,
        }

        self._conn.execute(
            """
            INSERT OR REPLACE INTO query_log
                (run_id, timestamp, user_role, query, collections,
                 retrieved, graded, sources, answer_len, outcome, error_msg)
            VALUES
                (:run_id, :timestamp, :user_role, :query, :collections,
                 :retrieved, :graded, :sources, :answer_len, :outcome, :error_msg)
            """,
            row,
        )
        self._conn.commit()
        logger.info(
            f"[GovernanceDB] logged run_id={row['run_id']} "
            f"outcome={outcome} role={row['user_role']!r}"
        )

    # ── Read ───────────────────────────────────────────────────────────────────

    def recent_runs(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the n most recent rows as plain dicts, newest first."""
        cursor = self._conn.execute(
            "SELECT * FROM query_log ORDER BY timestamp DESC LIMIT ?", (n,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def run_by_id(self, run_id: str) -> Optional[dict[str, Any]]:
        """Return a single row by run_id, or None if not found."""
        cursor = self._conn.execute(
            "SELECT * FROM query_log WHERE run_id = ?", (run_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def stats(self) -> dict[str, Any]:
        """Return aggregate statistics over all logged runs."""
        cursor = self._conn.execute(
            """
            SELECT
                COUNT(*)                          AS total_runs,
                SUM(CASE WHEN outcome='answered'   THEN 1 ELSE 0 END) AS answered,
                SUM(CASE WHEN outcome='no_results' THEN 1 ELSE 0 END) AS no_results,
                SUM(CASE WHEN outcome='error'      THEN 1 ELSE 0 END) AS errors,
                ROUND(AVG(graded), 2)             AS avg_graded_docs,
                ROUND(AVG(answer_len), 0)         AS avg_answer_len
            FROM query_log
            """
        )
        row = cursor.fetchone()
        return dict(row) if row else {}

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()
        logger.info("[GovernanceDB] connection closed.")

    def __enter__(self) -> "GovernanceDB":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
