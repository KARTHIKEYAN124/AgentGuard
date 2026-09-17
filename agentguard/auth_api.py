import os
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, field_validator

from .accounts import is_operator_token
from .models import Record

COOKIE = "agentguard_session"


class Credentials(Record):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value):
        return value.strip().casefold()


class Signup(Credentials):
    name: str = Field(min_length=1, max_length=60)


class WorkspaceName(Record):
    name: str = Field(min_length=1, max_length=80)


class InviteRequest(Record):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Literal["editor", "viewer"] = "viewer"


class TokenRequest(Record):
    token: str = Field(min_length=20, max_length=200)


class RoleRequest(Record):
    role: Literal["owner", "editor", "viewer"]


class LimitsRequest(Record):
    daily_runs: int = Field(ge=0, le=10000)
    daily_calls: int = Field(ge=0, le=100000)
    daily_budget: float = Field(ge=0, le=1000, allow_inf_nan=False)


class OperatorLimits(LimitsRequest):
    live_enabled: bool


class PasswordRequest(Record):
    current_password: str = Field(min_length=12, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


def check_origin(request):
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin")
    configured = os.getenv("AGENTGUARD_PUBLIC_URL")
    allowed = {configured.rstrip("/")} if configured else {str(request.base_url).rstrip("/")}
    if origin and origin.rstrip("/") not in allowed:
        raise HTTPException(403, "Cross-origin requests are not allowed")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site requests are not allowed")


def install_auth(app, accounts):
    router = APIRouter(prefix="/api/auth", tags=["Accounts and workspaces"])

    @app.middleware("http")
    async def request_safety(request, call_next):
        try:
            if request.url.path.startswith("/api/"):
                check_origin(request)
                length = request.headers.get("content-length")
                if length and int(length) > 2_000_000:
                    raise HTTPException(413, "Request exceeds the 2 MB limit")
        except (ValueError, HTTPException) as exc:
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"detail": exc.detail if isinstance(exc, HTTPException) else "Invalid request"},
                status_code=exc.status_code if isinstance(exc, HTTPException) else 400,
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def user(request):
        identity = accounts.user(request.cookies.get(COOKIE))
        if not identity:
            raise HTTPException(401, "Please sign in")
        return identity

    def owner(request, workspace_id):
        identity = user(request)
        member = accounts.membership(workspace_id, identity["id"])
        if member["role"] != "owner":
            raise HTTPException(403, "Only workspace owners can manage the team or limits")
        return member

    def operator(request):
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
        if is_operator_token(supplied):
            return
        identity = user(request)
        try:
            member = accounts.membership("legacy", identity["id"])
        except HTTPException as exc:
            raise HTTPException(403, "Operator access required") from exc
        if member["role"] != "owner":
            raise HTTPException(403, "Operator access required")

    def session_payload(identity):
        workspaces = accounts.workspaces(identity["id"]) if identity else []
        return {
            "user": identity,
            "workspaces": workspaces,
            "is_operator": any(w["id"] == "legacy" and w["role"] == "owner" for w in workspaces),
        }

    def set_cookie(response, request, raw):
        secure = urlsplit(os.getenv("AGENTGUARD_PUBLIC_URL", str(request.base_url))).scheme == "https"
        response.set_cookie(
            COOKIE, raw, max_age=14 * 86400, httponly=True, secure=secure, samesite="lax", path="/"
        )

    @router.get("/session")
    def session(request: Request):
        return session_payload(accounts.user(request.cookies.get(COOKIE)))

    @router.post("/signup", status_code=201)
    def signup(body: Signup, request: Request, response: Response):
        ip = request.client.host if request.client else "unknown"
        accounts.rate_limit("signup:" + ip, 5, 3600)
        raw = accounts.signup(body.email, body.name.strip() or "Member", body.password)
        set_cookie(response, request, raw)
        return session_payload(accounts.user(raw))

    @router.post("/login")
    def login(body: Credentials, request: Request, response: Response):
        ip = request.client.host if request.client else "unknown"
        accounts.rate_limit("login-ip:" + ip, 40, 300)
        accounts.rate_limit("login-email:" + body.email, 10, 300)
        raw = accounts.login(body.email, body.password)
        accounts.logout(request.cookies.get(COOKIE))
        set_cookie(response, request, raw)
        return session_payload(accounts.user(raw))

    @router.post("/logout", status_code=204)
    def logout(request: Request, response: Response):
        accounts.logout(request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")

    @router.post("/password", status_code=204)
    def password(body: PasswordRequest, request: Request, response: Response):
        identity = user(request)
        accounts.rate_limit("password:" + identity["id"], 5, 300)
        accounts.change_password(identity["id"], body.current_password, body.new_password)
        set_cookie(response, request, accounts.new_session(identity["id"]))

    @router.post("/workspaces", status_code=201)
    def create_workspace(body: WorkspaceName, request: Request):
        identity = user(request)
        return accounts.create_workspace(identity["id"], body.name)

    @router.post("/claim-original")
    def claim_original(body: TokenRequest, request: Request):
        identity = user(request)
        accounts.rate_limit("claim:" + identity["id"], 5, 300)
        if not is_operator_token(body.token):
            raise HTTPException(403, "Invalid original workspace token")
        return accounts.claim_legacy(identity["id"])

    @router.get("/workspaces/{workspace_id}")
    def workspace(workspace_id: str, request: Request):
        identity = user(request)
        member = accounts.membership(workspace_id, identity["id"])
        return {
            "workspace": member,
            "usage": accounts.usage(workspace_id),
            "members": accounts.members(workspace_id),
            "invitations": accounts.invitations(workspace_id) if member["role"] == "owner" else [],
        }

    @router.post("/workspaces/{workspace_id}/invitations", status_code=201)
    def invite(workspace_id: str, body: InviteRequest, request: Request):
        owner(request, workspace_id)
        accounts.rate_limit("invite:" + workspace_id, 20, 3600)
        return accounts.invite(workspace_id, body.email.strip().casefold(), body.role)

    @router.delete("/workspaces/{workspace_id}/invitations/{id}", status_code=204)
    def revoke(workspace_id: str, id: str, request: Request):
        owner(request, workspace_id)
        accounts.revoke_invitation(workspace_id, id)

    @router.post("/invitations/accept")
    def accept(body: TokenRequest, request: Request):
        identity = user(request)
        accounts.rate_limit("accept:" + identity["id"], 10, 300)
        return accounts.accept(identity, body.token)

    @router.patch("/workspaces/{workspace_id}/members/{id}")
    def role(workspace_id: str, id: str, body: RoleRequest, request: Request):
        owner(request, workspace_id)
        accounts.set_role(workspace_id, id, body.role)
        return {"updated": True}

    @router.delete("/workspaces/{workspace_id}/members/{id}", status_code=204)
    def remove_member(workspace_id: str, id: str, request: Request):
        owner(request, workspace_id)
        accounts.set_role(workspace_id, id, None)

    @router.patch("/workspaces/{workspace_id}/limits")
    def limits(workspace_id: str, body: LimitsRequest, request: Request):
        previous = owner(request, workspace_id)
        if any(getattr(body, key) > previous[key] for key in ("daily_runs", "daily_calls", "daily_budget")):
            raise HTTPException(403, "Owners can lower limits; increases require operator approval")
        accounts.set_limits(workspace_id, body.daily_runs, body.daily_calls, body.daily_budget)
        return accounts.workspace(workspace_id)

    @router.get("/operator/workspaces")
    def operator_workspaces(request: Request):
        operator(request)
        with accounts.store.connection() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM workspaces ORDER BY created_at DESC")]
        return [{**row, "usage": accounts.usage(row["id"])} for row in rows]

    @router.patch("/operator/workspaces/{workspace_id}")
    def operator_limits(workspace_id: str, body: OperatorLimits, request: Request):
        operator(request)
        accounts.workspace(workspace_id)
        accounts.set_limits(
            workspace_id, body.daily_runs, body.daily_calls, body.daily_budget, body.live_enabled
        )
        return accounts.workspace(workspace_id)

    app.include_router(router)
