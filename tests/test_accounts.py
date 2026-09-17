import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agentguard.accounts import Accounts, password_matches
from agentguard.api import create_app
from agentguard.auth_api import COOKIE
from agentguard.models import ModelSpec
from agentguard.providers import Completion
from agentguard.tenancy import BudgetedProvider

PASSWORD = "correct horse battery staple"


def test_existing_database_backed_up_before_account_migration(tmp_path):
    path = tmp_path / "original.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE preserved(value TEXT)")
        db.execute("INSERT INTO preserved VALUES('original data')")
    Accounts(str(path))
    backup = path.with_name(path.name + ".before-accounts.bak")
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT value FROM preserved").fetchone()[0] == "original data"
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
    Accounts(str(path))
    with sqlite3.connect(backup) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_API_TOKEN", "original-test-token-for-claim")
    monkeypatch.delenv("AGENTGUARD_PUBLIC_URL", raising=False)
    return create_app(str(tmp_path / "app.db"))


def signup(app, email):
    client = TestClient(app)
    response = client.post(
        "/api/auth/signup", json={"email": email, "name": email.split("@")[0], "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    session = response.json()
    ws = session["workspaces"][0]
    client.headers["X-Workspace-Id"] = ws["id"]
    return client, session["user"], ws


def test_signup_session_hashes_and_logout(app):
    c, user, w = signup(app, "owner@example.com")
    assert w["role"] == "owner" and not w["live_enabled"]
    assert c.get("/api/auth/session").json()["user"]["id"] == user["id"]
    with app.state.accounts.store.connection() as db:
        stored = db.execute("SELECT password FROM users WHERE id=?", (user["id"],)).fetchone()[0]
        raw_session = c.cookies.get(COOKIE)
        hashes = [r[0] for r in db.execute("SELECT hash FROM sessions")]
    assert stored != PASSWORD and password_matches(PASSWORD, stored)
    assert raw_session not in hashes
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/agents").status_code == 401
    assert c.get("/api/auth/session").json()["user"] is None


def test_login_failure_expiry_and_password_rotation(app):
    c, user, w = signup(app, "login@example.com")
    other = TestClient(app)
    assert (
        other.post(
            "/api/auth/login", json={"email": user["email"], "password": "wrong password for login"}
        ).status_code
        == 401
    )
    assert (
        other.post("/api/auth/login", json={"email": user["email"].upper(), "password": PASSWORD}).status_code
        == 200
    )
    response = c.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "another long secure password"},
    )
    assert response.status_code == 204
    assert other.get("/api/auth/session").json()["user"] is None
    assert c.get("/api/auth/session").json()["user"]["id"] == user["id"]
    with app.state.accounts.store.connection() as db:
        db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    assert c.get("/api/agents").status_code == 401


def test_secure_cookie_and_csrf(app, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_PUBLIC_URL", "https://testserver")
    c = TestClient(app, base_url="https://testserver")
    payload = {"email": "secure@example.com", "name": "Secure", "password": PASSWORD}
    blocked = c.post("/api/auth/signup", json=payload, headers={"Origin": "https://attacker.example"})
    assert blocked.status_code == 403
    response = c.post("/api/auth/signup", json=payload, headers={"Origin": "https://testserver"})
    assert response.status_code == 201
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert c.post("/api/auth/logout", headers={"Origin": "https://attacker.example"}).status_code == 403
    assert c.get("/api/auth/session").json()["user"]
    assert c.post("/api/auth/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_private_workspaces_and_all_record_ids_are_isolated(app):
    a, user_a, wa = signup(app, "alice@example.com")
    b, user_b, wb = signup(app, "bob@example.com")
    definition = {"name": "private", "version": "v1", "system_prompt": "Alice confidential prompt"}
    assert a.post("/api/agents", json=definition).status_code == 201
    assert b.get("/api/agents").json() == []
    assert b.get("/api/agents/private:v1").status_code == 404
    assert b.post("/api/runs", json={"agent_id": "private:v1", "input": "q"}).status_code == 404
    assert b.get("/api/agents", headers={"X-Workspace-Id": wa["id"]}).status_code == 404
    assert b.get(f"/api/auth/workspaces/{wa['id']}").status_code == 404
    assert b.post("/api/agents", json={**definition, "system_prompt": "Bob prompt"}).status_code == 201
    assert a.get("/api/agents/private:v1").json()["system_prompt"] == "Alice confidential prompt"
    assert app.state.accounts.path_for(wa["id"]) != app.state.accounts.path_for(wb["id"])
    assert a.get("/api/agents", headers={"X-Workspace-Id": "../../app"}).status_code == 404


def test_public_demo_is_read_only_and_never_contains_private_data(app):
    c, _, _ = signup(app, "private@example.com")
    c.post("/api/agents", json={"name": "secret-project", "version": "v1"})
    public = TestClient(app, headers={"X-AgentGuard-Demo": "true"})
    agents = public.get("/api/agents")
    assert agents.status_code == 200
    assert "secret-project" not in agents.text
    assert public.get("/api/overview").json()["summary"]["total_runs"] == 5
    assert public.post("/api/demo", json={}).status_code == 403
    assert public.post("/api/runs", json={"agent_id": "customer-support:v1", "input": "q"}).status_code == 403
    assert public.get("/api/auth/operator/workspaces").status_code == 401
    assert TestClient(app).get("/api/agents").status_code == 401


def invite(owner, ws, email, role="viewer"):
    response = owner.post(f"/api/auth/workspaces/{ws['id']}/invitations", json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


def test_invites_roles_revocation_and_last_owner(app):
    owner, owner_user, ws = signup(app, "owner@example.com")
    member, member_user, _ = signup(app, "member@example.com")
    invitation = invite(owner, ws, member_user["email"])
    assert member.post("/api/auth/invitations/accept", json={"token": invitation["token"]}).status_code == 200
    assert member.post("/api/auth/invitations/accept", json={"token": invitation["token"]}).status_code == 400
    member.headers["X-Workspace-Id"] = ws["id"]
    assert member.get("/api/agents").status_code == 200
    assert member.post("/api/demo", json={}).status_code == 403
    path = f"/api/auth/workspaces/{ws['id']}/members/{member_user['id']}"
    assert member.patch(path, json={"role": "owner"}).status_code == 403
    assert (
        member.post(
            f"/api/auth/workspaces/{ws['id']}/invitations", json={"email": "x@example.com"}
        ).status_code
        == 403
    )
    assert owner.patch(path, json={"role": "editor"}).status_code == 200
    assert member.post("/api/demo", json={}).status_code == 200
    assert (
        member.patch(
            f"/api/auth/workspaces/{ws['id']}/limits",
            json={"daily_runs": 1, "daily_calls": 1, "daily_budget": 0},
        ).status_code
        == 403
    )
    assert (
        owner.patch(
            f"/api/auth/workspaces/{ws['id']}/members/{owner_user['id']}", json={"role": "viewer"}
        ).status_code
        == 409
    )
    assert owner.delete(f"/api/auth/workspaces/{ws['id']}/members/{owner_user['id']}").status_code == 409
    assert owner.delete(path).status_code == 204
    assert member.get("/api/agents").status_code == 404


def test_invite_email_match_expiry_and_revoke(app):
    owner, _, ws = signup(app, "owner@example.com")
    member, _, _ = signup(app, "member@example.com")
    wrong = invite(owner, ws, "someone-else@example.com")
    assert member.post("/api/auth/invitations/accept", json={"token": wrong["token"]}).status_code == 400
    expired = invite(owner, ws, "member@example.com")
    with app.state.accounts.store.connection() as db:
        db.execute("UPDATE invitations SET expires=0 WHERE id=?", (expired["id"],))
    assert member.post("/api/auth/invitations/accept", json={"token": expired["token"]}).status_code == 400
    revoked = invite(owner, ws, "member@example.com")
    assert owner.delete(f"/api/auth/workspaces/{ws['id']}/invitations/{revoked['id']}").status_code == 204
    assert member.post("/api/auth/invitations/accept", json={"token": revoked["token"]}).status_code == 400


def test_original_workspace_claim_and_operator_separation(app):
    original = TestClient(app, headers={"Authorization": "Bearer original-test-token-for-claim"})
    assert original.post("/api/agents", json={"name": "original-private", "version": "v1"}).status_code == 201
    owner, _, ws = signup(app, "owner@example.com")
    stranger, _, ws2 = signup(app, "stranger@example.com")
    assert not owner.get("/api/agents").json()
    assert (
        owner.post("/api/auth/claim-original", json={"token": "wrong-but-long-enough-token"}).status_code
        == 403
    )
    assert (
        owner.post("/api/auth/claim-original", json={"token": "original-test-token-for-claim"}).status_code
        == 200
    )
    owner.headers["X-Workspace-Id"] = "legacy"
    assert owner.get("/api/agents/original-private:v1").status_code == 200
    assert owner.get("/api/auth/session").json()["is_operator"]
    assert stranger.get("/api/auth/operator/workspaces").status_code == 403
    assert (
        stranger.post("/api/auth/claim-original", json={"token": "original-test-token-for-claim"}).status_code
        == 409
    )
    assert original.get("/api/agents", headers={"X-Workspace-Id": ws2["id"]}).status_code == 403


def test_quota_enforced_and_owners_cannot_raise_limits(app):
    c, _, w = signup(app, "owner@example.com")
    assert c.post("/api/demo", json={}).status_code == 200
    limits = {"daily_runs": 1, "daily_calls": 5, "daily_budget": 0}
    assert c.patch(f"/api/auth/workspaces/{w['id']}/limits", json=limits).status_code == 200
    run = {"agent_id": "customer-support:v1", "input": "shipping"}
    assert c.post("/api/runs", json=run).status_code == 201
    assert c.post("/api/runs", json=run).status_code == 429
    assert (
        c.patch(f"/api/auth/workspaces/{w['id']}/limits", json={**limits, "daily_runs": 10000}).status_code
        == 403
    )
    assert (
        c.patch(f"/api/auth/operator/workspaces/{w['id']}", json={**limits, "live_enabled": True}).status_code
        == 403
    )
    assert app.state.accounts.usage(w["id"])["runs"] == 1


def test_atomic_budget_under_concurrency(app):
    c, _, w = signup(app, "owner@example.com")
    accounts = app.state.accounts
    accounts.set_limits(w["id"], 2, 2, 0.10, True)

    def reserve(_):
        try:
            accounts.reserve(w["id"], runs=1, calls=1, cost=0.05, live=True)
            return True
        except HTTPException:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        successes = list(pool.map(reserve, range(8)))
    assert sum(successes) == 2
    assert accounts.usage(w["id"])["reserved_cost"] == pytest.approx(0.1)


def test_live_requires_approval_and_operator_prices(app, monkeypatch):
    _, _, w = signup(app, "owner@example.com")
    calls = []

    class Provider:
        def complete(self, *args):
            calls.append(args)
            return Completion("answer")

    adapter = BudgetedProvider(app.state.accounts, w["id"], Provider())
    model = ModelSpec(provider="openai", model="approved", input_per_million=1, output_per_million=2)
    with pytest.raises(Exception, match="catalog"):
        adapter.complete(model, [], [])
    monkeypatch.setenv(
        "AGENTGUARD_MODEL_PRICES",
        json.dumps({"openai/approved": {"input_per_million": 1, "output_per_million": 2}}),
    )
    with pytest.raises(Exception, match="disabled"):
        adapter.complete(model, [], [])
    app.state.accounts.set_limits(w["id"], 5, 5, 1, True)
    adapter.complete(model, [{"role": "user", "content": "q"}], [])
    assert len(calls) == 1
    assert app.state.accounts.usage(w["id"])["reserved_cost"] > 0
    with pytest.raises(Exception, match="catalog"):
        adapter.complete(model.model_copy(update={"input_per_million": 0}), [], [])
    assert len(calls) == 1


def test_login_rate_limit(app):
    c, _, _ = signup(app, "owner@example.com")
    for _ in range(10):
        assert (
            c.post(
                "/api/auth/login", json={"email": "owner@example.com", "password": "wrong long password"}
            ).status_code
            == 401
        )
    assert (
        c.post("/api/auth/login", json={"email": "owner@example.com", "password": PASSWORD}).status_code
        == 429
    )


def test_accounts_persist_after_restart(app):
    c, user, ws = signup(app, "owner@example.com")
    reopened = Accounts(app.state.accounts.store.path)
    assert reopened.user(c.cookies.get(COOKIE))["id"] == user["id"]
    assert reopened.membership(ws["id"], user["id"])["role"] == "owner"


def test_parallel_request_context_isolation(app):
    a, _, wa = signup(app, "a@example.com")
    b, _, wb = signup(app, "b@example.com")
    a.post("/api/agents", json={"name": "alice-only", "version": "v1"})
    b.post("/api/agents", json={"name": "bob-only", "version": "v1"})

    def query(pair):
        client, expected = pair
        assert client.get("/api/agents").json()[0]["name"] == expected

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(query, [(a, "alice-only"), (b, "bob-only")] * 8))
