from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import TERMINAL, Event, Incident, State, validate_transition


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """Single-process SQLite store; event and incident updates commit atomically."""

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL,
              data TEXT NOT NULL, FOREIGN KEY(incident_id) REFERENCES incidents(id));
            CREATE INDEX IF NOT EXISTS events_incident ON events(incident_id, id);
        """)

    def create(self) -> Incident:
        ident = uuid.uuid4().hex[:16]
        incident = Incident(id=ident, state=State.IDLE, created_at=now(), updated_at=now(),
                            summary="Incident queued", correlation_id=f"incident-{ident}")
        with self.db:
            self.db.execute("INSERT INTO incidents VALUES (?, ?)", (ident, incident.model_dump_json()))
        return incident

    def get(self, ident: str) -> Incident:
        result = self._snapshot(ident)
        result.events = self.events(ident)
        return result

    def _snapshot(self, ident: str) -> Incident:
        row = self.db.execute("SELECT data FROM incidents WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise KeyError(ident)
        return Incident.model_validate_json(row["data"])

    def list(self) -> list[Incident]:
        return [Incident.model_validate_json(row["data"]) for row in self.db.execute(
            "SELECT data FROM incidents ORDER BY rowid DESC LIMIT 100")]

    def events(self, ident: str, after: int = 0) -> list[Event]:
        return [Event.model_validate({**json.loads(row["data"]), "id": row["id"]}) for row in
                self.db.execute("SELECT id,data FROM events WHERE incident_id=? AND id>? ORDER BY id",
                                (ident, after))]

    def update(self, ident: str, *, state: State | None = None, summary: str,
               tool_status: str = "info", outputs: dict | None = None, error: str | None = None,
               artifacts: dict | None = None, attempt: int | None = None,
               reset_artifacts: bool = False, correlation_id: str | None = None) -> Incident:
        incident = self._snapshot(ident)
        target = state or incident.state
        validate_transition(incident.state, target)
        if target != incident.state or incident.state not in TERMINAL:
            incident.summary = summary
            incident.error = error
        incident.state = target
        incident.updated_at = now()
        if reset_artifacts:
            incident.artifacts.clear()
        if artifacts:
            incident.artifacts.update(artifacts)
        if attempt is not None:
            incident.attempt = attempt
        if correlation_id is not None:
            incident.correlation_id = correlation_id
        event = Event(id=0, incident_id=ident, timestamp=incident.updated_at, state=target,
                      summary=summary, tool_status=tool_status, outputs=outputs or {}, error=error)
        with self.db:
            self.db.execute("INSERT INTO events(incident_id,data) VALUES (?, ?)",
                            (ident, event.model_dump_json(exclude={"id"})))
            self.db.execute("UPDATE incidents SET data=? WHERE id=?",
                            (incident.model_dump_json(exclude={"events"}), ident))
        return self.get(ident)

    def close(self):
        self.db.close()
