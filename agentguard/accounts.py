"""Persistent identities, opaque sessions, workspace membership, and atomic quotas."""

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .storage import Store


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"{salt}:{derived}"


def password_matches(password, encoded):
    return hmac.compare_digest(hash_password(password, encoded.split(":", 1)[0]), encoded)


class Accounts:
    def __init__(self, path):
        existing = Path(path)
        if existing.is_file():
            with sqlite3.connect(existing) as source:
                migrated = source.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
                ).fetchone()
                if not migrated:
                    backup = existing.with_name(existing.name + ".before-accounts.bak")
                    if not backup.exists():
                        with sqlite3.connect(backup) as destination:
                            source.backup(destination)
        self.store = Store(path)
        self.root = Path(path).resolve().parent / "workspaces"
        self.root.mkdir(exist_ok=True)
        with self.store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    password TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL,
                    live_enabled INTEGER NOT NULL DEFAULT 0,
                    daily_runs INTEGER NOT NULL DEFAULT 100,
                    daily_calls INTEGER NOT NULL DEFAULT 500,
                    daily_budget REAL NOT NULL DEFAULT 1.0);
                CREATE TABLE IF NOT EXISTS memberships (
                    workspace_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
                    PRIMARY KEY(workspace_id,user_id));
                CREATE TABLE IF NOT EXISTS invitations (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, email TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('editor','viewer')),
                    hash TEXT UNIQUE NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS usage_daily (
                    workspace_id TEXT NOT NULL, day TEXT NOT NULL, runs INTEGER NOT NULL DEFAULT 0,
                    calls INTEGER NOT NULL DEFAULT 0, reserved_cost REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY(workspace_id,day));
                CREATE TABLE IF NOT EXISTS rate_limits (
                    bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
            """)
            db.execute(
                "INSERT OR IGNORE INTO workspaces(id,name,created_at,live_enabled,daily_runs,daily_calls,daily_budget) VALUES('legacy','Original workspace',?,1,500,3000,5)",
                (time.time(),),
            )

    def rate_limit(self, key, limit, seconds):
        timestamp = time.time()
        bucket = token_hash(key + str(int(timestamp // seconds)))
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM rate_limits WHERE expires < ?", (timestamp,))
            db.execute(
                "INSERT INTO rate_limits(bucket,count,expires) VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1",
                (bucket, timestamp + seconds),
            )
            count = db.execute("SELECT count FROM rate_limits WHERE bucket=?", (bucket,)).fetchone()[0]
        if count > limit:
            raise HTTPException(429, "Too many attempts. Please try again later.")

    def signup(self, email, name, password):
        user_id, workspace_id = uuid4().hex, uuid4().hex
        encoded = hash_password(password)
        try:
            with self.store.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO users VALUES(?,?,?,?,?)", (user_id, email, name, encoded, time.time())
                )
                db.execute(
                    "INSERT INTO workspaces(id,name,created_at) VALUES(?,?,?)",
                    (workspace_id, f"{name}'s workspace", time.time()),
                )
                db.execute("INSERT INTO memberships VALUES(?,?, 'owner')", (workspace_id, user_id))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Unable to create this account. Try signing in instead.") from exc
        return self.new_session(user_id)

    def login(self, email, password):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        # Perform the same expensive derivation for unknown accounts.
        dummy = "0" * 32 + ":" + "0" * 128
        valid = password_matches(password, row["password"] if row else dummy)
        if not row or not valid:
            raise HTTPException(401, "Email or password is incorrect")
        return self.new_session(row["id"])

    def new_session(self, user_id):
        raw = secrets.token_urlsafe(32)
        with self.store.connection() as db:
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)", (token_hash(raw), user_id, time.time() + 14 * 86400)
            )
        return raw

    def user(self, raw):
        if not raw:
            return None
        with self.store.connection() as db:
            row = db.execute(
                "SELECT u.id,u.email,u.name FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.hash=? AND s.expires>?",
                (token_hash(raw), time.time()),
            ).fetchone()
        return dict(row) if row else None

    def logout(self, raw):
        with self.store.connection() as db:
            db.execute("DELETE FROM sessions WHERE hash=?", (token_hash(raw or ""),))

    def change_password(self, user_id, current, new):
        with self.store.connection() as db:
            row = db.execute("SELECT password FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or not password_matches(current, row["password"]):
                raise HTTPException(400, "Current password is incorrect")
            db.execute("UPDATE users SET password=? WHERE id=?", (hash_password(new), user_id))
            db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    def workspaces(self, user_id):
        with self.store.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT w.*,m.role FROM workspaces w JOIN memberships m ON m.workspace_id=w.id WHERE m.user_id=? ORDER BY w.created_at",
                    (user_id,),
                )
            ]

    def membership(self, workspace_id, user_id):
        with self.store.connection() as db:
            row = db.execute(
                "SELECT w.*,m.role FROM workspaces w JOIN memberships m ON m.workspace_id=w.id WHERE w.id=? AND m.user_id=?",
                (workspace_id, user_id),
            ).fetchone()
        if not row:
            raise HTTPException(404, "Workspace not found")
        return dict(row)

    def workspace(self, id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM workspaces WHERE id=?", (id,)).fetchone()
        if not row:
            raise HTTPException(404, "Workspace not found")
        return dict(row)

    def create_workspace(self, user_id, name):
        id = uuid4().hex
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                "SELECT COUNT(*) FROM memberships WHERE user_id=? AND role='owner'", (user_id,)
            ).fetchone()[0]
            if count >= 5:
                raise HTTPException(403, "An account can own at most five workspaces")
            db.execute("INSERT INTO workspaces(id,name,created_at) VALUES(?,?,?)", (id, name, time.time()))
            db.execute("INSERT INTO memberships VALUES(?,?, 'owner')", (id, user_id))
        return self.membership(id, user_id)

    def members(self, workspace_id):
        with self.store.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT u.id,u.name,u.email,m.role FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=? ORDER BY u.name",
                    (workspace_id,),
                )
            ]

    def set_role(self, workspace_id, target_id, role):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT role FROM memberships WHERE workspace_id=? AND user_id=?", (workspace_id, target_id)
            ).fetchone()
            if not existing:
                raise HTTPException(404, "Member not found")
            owners = db.execute(
                "SELECT COUNT(*) FROM memberships WHERE workspace_id=? AND role='owner'", (workspace_id,)
            ).fetchone()[0]
            if existing["role"] == "owner" and role != "owner" and owners <= 1:
                raise HTTPException(409, "A workspace must retain at least one owner")
            if role is None:
                db.execute(
                    "DELETE FROM memberships WHERE workspace_id=? AND user_id=?", (workspace_id, target_id)
                )
            else:
                db.execute(
                    "UPDATE memberships SET role=? WHERE workspace_id=? AND user_id=?",
                    (role, workspace_id, target_id),
                )

    def invite(self, workspace_id, email, role):
        raw, id = secrets.token_urlsafe(32), uuid4().hex
        expires = time.time() + 7 * 86400
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                "SELECT COUNT(*) FROM invitations WHERE workspace_id=? AND used=0 AND expires>?",
                (workspace_id, time.time()),
            ).fetchone()[0]
            if count >= 30:
                raise HTTPException(429, "Too many pending invitations")
            db.execute(
                "UPDATE invitations SET used=1 WHERE workspace_id=? AND email=?", (workspace_id, email)
            )
            db.execute(
                "INSERT INTO invitations VALUES(?,?,?,?,?,?,0)",
                (id, workspace_id, email, role, token_hash(raw), expires),
            )
        return {"id": id, "email": email, "role": role, "expires": expires, "token": raw}

    def invitations(self, workspace_id):
        with self.store.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,email,role,expires FROM invitations WHERE workspace_id=? AND used=0 AND expires>?",
                    (workspace_id, time.time()),
                )
            ]

    def revoke_invitation(self, workspace_id, id):
        with self.store.connection() as db:
            db.execute("UPDATE invitations SET used=1 WHERE workspace_id=? AND id=?", (workspace_id, id))

    def accept(self, user, raw):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            invite = db.execute(
                "SELECT * FROM invitations WHERE hash=? AND used=0 AND expires>?",
                (token_hash(raw), time.time()),
            ).fetchone()
            if not invite or invite["email"] != user["email"]:
                raise HTTPException(400, "Invitation is invalid, expired, or belongs to another email")
            db.execute(
                "INSERT OR IGNORE INTO memberships VALUES(?,?,?)",
                (invite["workspace_id"], user["id"], invite["role"]),
            )
            db.execute("UPDATE invitations SET used=1 WHERE id=?", (invite["id"],))
        return self.membership(invite["workspace_id"], user["id"])

    def claim_legacy(self, user_id):
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute(
                "SELECT user_id FROM memberships WHERE workspace_id='legacy' AND role='owner'"
            ).fetchone()
            if owner and owner["user_id"] != user_id:
                raise HTTPException(409, "Original workspace has already been claimed")
            db.execute("INSERT OR IGNORE INTO memberships VALUES('legacy',?,'owner')", (user_id,))
        return self.membership("legacy", user_id)

    def usage(self, workspace_id):
        day = datetime.now(UTC).date().isoformat()
        with self.store.connection() as db:
            row = db.execute(
                "SELECT * FROM usage_daily WHERE workspace_id=? AND day=?", (workspace_id, day)
            ).fetchone()
        return dict(row) if row else {"day": day, "runs": 0, "calls": 0, "reserved_cost": 0.0}

    def reserve(self, workspace_id, *, runs=0, calls=0, cost=0.0, live=False):
        day = datetime.now(UTC).date().isoformat()
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            config = db.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
            if live and not config["live_enabled"]:
                raise HTTPException(
                    403, "Live AI is disabled for this workspace. An operator must enable it."
                )
            db.execute("INSERT OR IGNORE INTO usage_daily(workspace_id,day) VALUES(?,?)", (workspace_id, day))
            usage = db.execute(
                "SELECT * FROM usage_daily WHERE workspace_id=? AND day=?", (workspace_id, day)
            ).fetchone()
            if (
                usage["runs"] + runs > config["daily_runs"]
                or usage["calls"] + calls > config["daily_calls"]
                or usage["reserved_cost"] + cost > config["daily_budget"] + 1e-12
            ):
                raise HTTPException(429, "Workspace daily usage limit reached. Limits reset at 00:00 UTC.")
            db.execute(
                "UPDATE usage_daily SET runs=runs+?,calls=calls+?,reserved_cost=reserved_cost+? WHERE workspace_id=? AND day=?",
                (runs, calls, cost, workspace_id, day),
            )

    def set_limits(self, workspace_id, runs, calls, budget, live_enabled=None):
        with self.store.connection() as db:
            db.execute(
                "UPDATE workspaces SET daily_runs=?,daily_calls=?,daily_budget=? WHERE id=?",
                (runs, calls, budget, workspace_id),
            )
            if live_enabled is not None:
                db.execute(
                    "UPDATE workspaces SET live_enabled=? WHERE id=?", (int(live_enabled), workspace_id)
                )

    def path_for(self, workspace_id):
        if workspace_id == "legacy":
            return self.store.path
        # Only persisted, server-issued UUIDs can reach the filesystem.
        self.workspace(workspace_id)
        if len(workspace_id) != 32 or any(c not in "0123456789abcdef" for c in workspace_id):
            raise HTTPException(400, "Invalid workspace ID")
        return str(self.root / (workspace_id + ".db"))


def is_operator_token(value):
    expected = os.getenv("AGENTGUARD_API_TOKEN", "")
    return bool(expected and value and secrets.compare_digest(value.encode(), expected.encode()))
