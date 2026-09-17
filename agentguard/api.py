import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jsonschema.exceptions import SchemaError
from pydantic import Field

from .accounts import Accounts, is_operator_token
from .auth_api import COOKIE, install_auth
from .demo import seed_demo
from .evaluations import detect_regression, evaluate_faithfulness, evaluate_retrieval, evaluate_schema
from .models import (
    AgentConfig,
    Dataset,
    ExecuteRequest,
    ExperimentRequest,
    JudgeRequest,
    Metrics,
    ModelSpec,
    PromptRequest,
    Record,
    SuiteRequest,
)
from .providers import ProviderError
from .service import AgentGuard
from .tenancy import WorkspaceGuard
from .tracing import configure_telemetry


class SchemaRequest(Record):
    output: str | dict
    json_schema: dict


class FaithfulnessRequest(Record):
    answer: str = Field(max_length=50000)
    sources: list[str] = Field(max_length=1000)


class RetrievalRequest(Record):
    query: str
    expected_docs: list[str]
    retrieved_docs: list[str]
    k: int = Field(default=5, ge=1, le=1000)


class RegressionRequest(Record):
    current: Metrics
    baseline: Metrics


class RunJudgeRequest(Record):
    model: ModelSpec
    rubric: str = Field(default="Assess correctness, relevance, safety, and completeness.", max_length=10000)


def create_app(db_path=None, provider=None):
    path = db_path or os.getenv("AGENTGUARD_DB", "data/agentguard.db")
    accounts = Accounts(path)
    legacy_guard = AgentGuard(path, provider)
    demo_guard = AgentGuard(str(Path(path).parent / "public-demo.db"))
    seed_demo(demo_guard)
    if not demo_guard.store.list("suites", 1):
        demo_guard.run_regression_suite("customer-support:v1", "support-gold:v1")
    selected_guard = ContextVar("workspace_guard")

    class ScopedGuard:
        def __getattr__(self, name):
            return getattr(selected_guard.get(), name)

    guard = ScopedGuard()

    @asynccontextmanager
    async def lifespan(app):
        telemetry = configure_telemetry()
        yield
        telemetry.shutdown()

    app = FastAPI(
        title="AgentGuard",
        version="0.2.0",
        description="Private agent workspaces, team roles, evaluation, and observability. Costs are USD estimates.",
        lifespan=lifespan,
    )
    app.state.guard = legacy_guard
    app.state.accounts = accounts
    install_auth(app, accounts)

    async def authorize(request: Request):
        requested_id = request.headers.get("x-workspace-id")
        if request.headers.get("x-agentguard-demo") == "true":
            if request.method != "GET":
                raise HTTPException(
                    403, "The public demo is read-only. Create an account to run your own agents."
                )
            current = demo_guard
        elif request.headers.get("authorization"):
            supplied = request.headers["authorization"]
            if not supplied.startswith("Bearer ") or not is_operator_token(supplied[7:]):
                raise HTTPException(401, "A valid workspace API token is required")
            if requested_id and requested_id != "legacy":
                raise HTTPException(403, "The original token grants access only to the original workspace")
            current = WorkspaceGuard(accounts, "legacy", provider)
        else:
            identity = accounts.user(request.cookies.get(COOKIE))
            if not identity:
                raise HTTPException(
                    401, "Sign in to access your private workspace, or explore the public demo"
                )
            spaces = accounts.workspaces(identity["id"])
            workspace_id = requested_id or (spaces[0]["id"] if spaces else "")
            member = accounts.membership(workspace_id, identity["id"])
            if request.method != "GET" and member["role"] == "viewer":
                raise HTTPException(403, "Viewers have read-only access. Ask an owner for editor access.")
            accounts.rate_limit("workspace-requests:" + workspace_id, 1000, 60)
            current = WorkspaceGuard(accounts, workspace_id, provider)
        binding = selected_guard.set(current)
        try:
            yield
        finally:
            selected_guard.reset(binding)

    @app.exception_handler(KeyError)
    async def not_found(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(SchemaError)
    async def invalid_schema(request, exc):
        return JSONResponse(status_code=422, content={"detail": "Invalid JSON Schema: " + exc.message})

    @app.exception_handler(ProviderError)
    async def provider_failure(request, exc):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "auth_required": bool(os.getenv("AGENTGUARD_API_TOKEN"))}

    from fastapi import APIRouter

    router = APIRouter(prefix="/api", dependencies=[Depends(authorize)])

    @router.get("/overview")
    def overview():
        runs = guard.store.list("runs", 1000000)
        suites = guard.store.list("suites", 10)
        return {
            "summary": guard.summarize(runs),
            "recent_runs": runs[:12],
            "recent_suites": suites,
            "agent_count": len(guard.store.list("agents", 1000000)),
        }

    @router.get("/providers")
    def providers():
        workspace_id = getattr(guard, "workspace_id", None)
        live_enabled = bool(workspace_id and accounts.workspace(workspace_id)["live_enabled"])
        return {
            "demo": True,
            **{
                p: bool(os.getenv(key)) and live_enabled
                for p, key in [
                    ("openai", "OPENAI_API_KEY"),
                    ("anthropic", "ANTHROPIC_API_KEY"),
                    ("gemini", "GEMINI_API_KEY"),
                ]
            },
        }

    @router.post("/demo")
    def demo():
        return seed_demo(guard)

    @router.post("/agents", status_code=201)
    def register_agent(request: AgentConfig):
        return guard.register_agent(request)

    @router.post("/runs", status_code=201)
    def execute_agent(request: ExecuteRequest):
        return guard.execute_agent(
            request.input,
            request.agent_id,
            request.task,
            request.session_id,
            request.experiment_id,
            request.subject_id,
        )

    @router.post("/agents/{agent_id}/route")
    def route_model(agent_id: str, task: str = "extraction"):
        if task not in ("extraction", "reasoning"):
            raise ValueError("task must be extraction or reasoning")
        agent = guard.store.get("agents", agent_id)
        config = AgentConfig.model_validate({k: v for k, v in agent.items() if k in AgentConfig.model_fields})
        return [s.model_dump() for s in guard.route_model(task, config)]

    @router.delete("/agents/{agent_id}/memory/{session_id}", status_code=204)
    def clear_memory(agent_id: str, session_id: str):
        guard.store.get("agents", agent_id)
        guard.store.clear_memory(agent_id, session_id)

    @router.post("/prompts", status_code=201)
    def prompt_version(request: PromptRequest):
        return guard.prompt_version(request.name, request.version, request.template)

    @router.get("/prompts/{prompt_id}/results")
    def prompt_results(prompt_id: str):
        return {
            "prompt": guard.store.get("prompts", prompt_id),
            "suites": [s for s in guard.store.list("suites", 1000000) if s.get("prompt_id") == prompt_id],
        }

    @router.post("/datasets", status_code=201)
    def dataset(request: Dataset):
        return guard.create_dataset(request)

    @router.post("/suites", status_code=201)
    def run_regression_suite(request: SuiteRequest):
        return guard.run_regression_suite(
            request.agent_id, request.dataset_id, request.baseline_id, request.judge_model
        )

    @router.post("/evaluations/schema")
    def schema(request: SchemaRequest):
        return evaluate_schema(request.output, request.json_schema)

    @router.post("/evaluations/faithfulness")
    def faithfulness(request: FaithfulnessRequest):
        return evaluate_faithfulness(request.answer, request.sources)

    @router.post("/evaluations/retrieval")
    def retrieval(request: RetrievalRequest):
        return evaluate_retrieval(**request.model_dump())

    @router.post("/evaluations/judge")
    def llm_judge(request: JudgeRequest):
        return guard.llm_judge(
            request.input, request.response, request.rubric, request.model, request.sources
        )

    @router.post("/runs/{run_id}/judge")
    def judge_run(run_id: str, request: RunJudgeRequest):
        return guard.judge_run(run_id, request.model, request.rubric)

    @router.post("/evaluations/regression")
    def regression(request: RegressionRequest):
        return detect_regression(request.current, request.baseline)

    @router.post("/experiments", status_code=201)
    def ab_test(request: ExperimentRequest):
        return guard.ab_test(**request.model_dump())

    @router.get("/experiments/{experiment_id}/results")
    def experiment_results(experiment_id: str):
        return guard.experiment_results(experiment_id)

    @router.get("/{kind}")
    def records(kind: str, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0)):
        if kind not in {"agents", "runs", "prompts", "datasets", "suites", "experiments", "judgments"}:
            raise HTTPException(404)
        return guard.store.list(kind, limit, offset)

    @router.get("/{kind}/{id}")
    def record(kind: str, id: str):
        if kind not in {"agents", "runs", "prompts", "datasets", "suites", "experiments", "judgments"}:
            raise HTTPException(404)
        return guard.store.get(kind, id)

    app.include_router(router)
    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def dashboard():
            return FileResponse(dist / "index.html")
    else:

        @app.get("/")
        def dashboard_setup():
            return {
                "message": "Build the frontend with npm ci and npm run build in frontend/, then restart.",
                "api_docs": "/docs",
            }

    return app
