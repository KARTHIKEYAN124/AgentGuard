import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    """Small, durable single-workspace store. Each operation owns its connection."""

    def __init__(self, path: str = "data/agentguard.db"):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    PRIMARY KEY(kind, id));
                CREATE INDEX IF NOT EXISTS records_time ON records(kind, created_at);
                CREATE TABLE IF NOT EXISTS memory (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT NOT NULL,
                    session_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS memory_session ON memory(agent_id,session_id,seq);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, kind, id, body, *, replace=False):
        with self.connection() as db:
            try:
                if replace:
                    db.execute(
                        "UPDATE records SET body=? WHERE kind=? AND id=?", (json.dumps(body), kind, id)
                    )
                else:
                    db.execute(
                        "INSERT INTO records(kind,id,body) VALUES(?,?,?)", (kind, id, json.dumps(body))
                    )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"{kind} {id} already exists; create a new version") from exc
        return body

    def get(self, kind, id):
        with self.connection() as db:
            row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, id)).fetchone()
        if row is None:
            raise KeyError(f"{kind} {id} not found")
        return json.loads(row["body"])

    def list(self, kind, limit=200, offset=0):
        with self.connection() as db:
            rows = db.execute(
                "SELECT body FROM records WHERE kind=? ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
                (kind, limit, offset),
            ).fetchall()
        return [json.loads(row["body"]) for row in rows]

    def history(self, agent_id, session_id):
        with self.connection() as db:
            rows = db.execute(
                "SELECT body FROM memory WHERE agent_id=? AND session_id=? ORDER BY seq DESC LIMIT 10",
                (agent_id, session_id),
            ).fetchall()
        return [m for row in reversed(rows) for m in json.loads(row["body"])]

    def remember(self, agent_id, session_id, input, output):
        with self.connection() as db:
            db.execute(
                "INSERT INTO memory(agent_id,session_id,body) VALUES(?,?,?)",
                (
                    agent_id,
                    session_id,
                    json.dumps(
                        [{"role": "user", "content": input}, {"role": "assistant", "content": output}]
                    ),
                ),
            )
            db.execute(
                "DELETE FROM memory WHERE agent_id=? AND session_id=? AND seq NOT IN (SELECT seq FROM memory WHERE agent_id=? AND session_id=? ORDER BY seq DESC LIMIT 10)",
                (agent_id, session_id, agent_id, session_id),
            )

    def clear_memory(self, agent_id, session_id):
        with self.connection() as db:
            db.execute("DELETE FROM memory WHERE agent_id=? AND session_id=?", (agent_id, session_id))
