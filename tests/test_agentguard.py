import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError

from agentguard.api import create_app
from agentguard.demo import seed_demo
from agentguard.evaluations import (
    detect_regression,
    evaluate_faithfulness,
    evaluate_retrieval,
    evaluate_schema,
)
from agentguard.models import AgentConfig, Dataset, Document, GoldCase, ModelSpec
from agentguard.providers import Completion, ProviderClient, ProviderError, cost_of
from agentguard.service import AgentGuard


@pytest.fixture
def guard(tmp_path):
    return AgentGuard(str(tmp_path / "test.db"))


@pytest.fixture
def demo(guard):
    seed_demo(guard)
    return guard


@pytest.mark.parametrize(
    "question",
    [
        "Can I return an used item?",
        "Can I return a used item?",
        "Can I return an item that is not unused?",
    ],
)
def test_demo_does_not_infer_used_item_eligibility(demo, question):
    run = demo.execute_agent(question, "customer-support:v2")
    assert run["status"] == "success"
    assert run["output"] == (
        "The supplied policy covers unused items. "
        "I cannot determine whether a used item is eligible for return from this evidence."
    )
    unused = demo.execute_agent("Can I return an unused item?", "customer-support:v2")
    assert unused["output"] == "You can return an unused item within 30 days of delivery."


def test_lexical_match_is_not_question_relevance():
    policy = "You can return an unused item within 30 days of delivery."
    result = evaluate_faithfulness(policy, [policy])
    assert result["score"] == 1
    assert "does not establish answer correctness or relevance" in result["warning"]


def test_immutable_agent_and_prompt_versions(guard):
    p = guard.prompt_version("test", "v1", "Use evidence")
    a = guard.register_agent("support", "v1", prompt_id=p["id"])
    assert a["system_prompt"] == "Use evidence"
    with pytest.raises(ValueError, match="already exists"):
        guard.register_agent("support", "v1")
    with pytest.raises(ValueError):
        guard.prompt_version("test", "v1", "Changed")
    reopened = AgentGuard(guard.store.path)
    assert reopened.store.get("agents", a["id"]) == a


def test_schema_pydantic_strict_and_json_schema():
    class Customer(BaseModel):
        customer_id: int

    assert evaluate_schema('{"customer_id":123}', Customer)["passed"]
    assert not evaluate_schema('{"customer_id":"123"}', Customer)["passed"]
    assert not evaluate_schema("not json", Customer)["passed"]
    assert not evaluate_schema('{"id":"123"}', {"type": "object", "required": ["customer_id"]})["passed"]


def test_faithfulness_is_explicit_screening():
    result = evaluate_faithfulness("The moon is cheese.", ["Returns take 30 days."])
    assert result["method"] == "lexical_overlap"
    assert result["unsupported_claims"]
    assert "not proof" in result["warning"]
    assert evaluate_faithfulness("Answer", [])["score"] is None
    assert evaluate_faithfulness("", ["Evidence"])["score"] is None


def test_retrieval_duplicates_and_missing_expected():
    result = evaluate_retrieval("q", ["b", "c"], ["a", "b", "b", "c"], 3)
    assert result["precision_at_k"] == pytest.approx(2 / 3)
    assert result["recall_at_k"] == 1
    assert result["mrr"] == 0.5
    assert evaluate_retrieval("q", ["b"], ["b"], 5)["precision_at_k"] == 0.2
    assert evaluate_retrieval("q", [], [], 3)["recall_at_k"] is None
    with pytest.raises(ValueError):
        evaluate_retrieval("q", [], [], 0)


@pytest.mark.parametrize(
    "metric,value,passes",
    [
        ("accuracy", 0.88, True),
        ("accuracy", 0.879, False),
        ("cost", 1.2, True),
        ("cost", 1.201, False),
        ("latency_ms", 130, True),
        ("latency_ms", 130.1, False),
    ],
)
def test_regression_boundaries(metric, value, passes):
    baseline = {"accuracy": 0.91, "cost": 1, "latency_ms": 100}
    current = {**baseline, metric: value}
    assert detect_regression(current, baseline)["passed"] == passes


def test_gate_unknown_zero_and_invalid_values():
    base = {"accuracy": 1, "cost": 0, "latency_ms": 0}
    assert detect_regression(base, base)["passed"]
    assert not detect_regression({**base, "cost": 0.001}, base)["passed"]
    assert not detect_regression({**base, "cost": None}, base)["passed"]
    with pytest.raises(ValidationError):
        detect_regression({**base, "accuracy": float("nan")}, base)


def test_runtime_retrieval_memory_and_trace(demo):
    run = demo.execute_agent("Can I return an unused item?", "customer-support:v1", session_id="one")
    assert run["status"] == "success"
    assert run["retrieval"][0]["id"] == "returns"
    assert "30 days" in run["output"]
    assert run["cost"] == 0
    assert run["usage_estimated"]
    assert run["spans"][0]["parent_id"] is None
    assert all(s["parent_id"] == run["spans"][0]["id"] for s in run["spans"][1:])
    assert demo.trace_run(run["id"]) == run
    assert demo.store.history("customer-support:v1", "one")
    assert not demo.store.history("customer-support:v2", "one")
    assert not demo.store.history("customer-support:v1", "two")
    demo.store.clear_memory("customer-support:v1", "one")
    assert not demo.store.history("customer-support:v1", "one")


def test_real_tool_loop(demo):
    run = demo.execute_agent("Look up order 123", "customer-support:v1")
    assert run["status"] == "success"
    assert json.loads(run["output"])["status"] == "shipped"
    assert run["tool_calls"][0]["status"] == "ok"
    assert run["tool_calls"][0]["output"]["source"] == "demo_fixture"
    assert len([s for s in run["spans"] if s["name"] == "llm.generate"]) == 2


def test_router_reasoning_and_fallback(guard):
    cheap = ModelSpec(provider="openai", model="cheap")
    strong = ModelSpec(provider="anthropic", model="strong")
    config = AgentConfig(
        name="router", version="v1", model=cheap, reasoning_model=strong, fallbacks=[ModelSpec()]
    )
    assert guard.route_model("extraction", config)[0] == cheap
    assert guard.route_model("reasoning", config)[0] == strong

    class Outage(ProviderClient):
        def complete(self, spec, *args):
            if spec.provider != "demo":
                raise ProviderError("Outage", retryable=True)
            return super().complete(spec, *args)

    guard.provider = Outage()
    guard.register_agent(config)
    run = guard.execute_agent("Compare the options", "router:v1")
    assert run["status"] == "success"
    assert run["provider"] == "demo"
    assert any(s["status"] == "error" for s in run["spans"])


def test_failed_run_is_persisted(guard):
    class Broken:
        def complete(self, *args):
            raise ProviderError("HTTP 401", retryable=False)

    guard.provider = Broken()
    guard.register_agent("broken", "v1")
    run = guard.execute_agent("Hello", "broken:v1")
    assert run["status"] == "error"
    assert demo_error_spans(run)
    assert guard.store.get("runs", run["id"])["error"] == "HTTP 401"


def demo_error_spans(run):
    return any(s["status"] == "error" for s in run["spans"])


@pytest.mark.parametrize("mode", ["unknown", "bad_arguments", "loop"])
def test_tools_are_allowlisted_and_bounded(guard, mode):
    class BadTool:
        def complete(self, *args):
            return Completion(
                calls=[
                    {
                        "id": "x",
                        "type": "function",
                        "function": {
                            "name": "shell" if mode == "unknown" else "lookup_order",
                            "arguments": '{"order_id":3}'
                            if mode == "bad_arguments"
                            else '{"order_id":"123"}',
                        },
                    }
                ]
            )

    guard.provider = BadTool()
    guard.register_agent("bounded", "v1", tools=["lookup_order"], max_steps=2)
    run = guard.execute_agent("Hi", "bounded:v1")
    assert run["status"] == "error"
    assert len(run["tool_calls"]) <= 2


def test_full_suite_and_snapshot(demo):
    suite = demo.run_regression_suite("customer-support:v1", "support-gold:v1")
    assert suite["passed"]
    assert len(suite["cases"]) == 5
    assert suite["metrics"]["accuracy"] == 1
    assert suite["dataset_snapshot"]["cases"]
    assert suite["agent_snapshot"]["prompt_id"] == "support:v1"
    assert suite["evaluation_config"]["accuracy"] == "normalized_exact_match_and_schema"
    # Stable synthetic timing prevents machine scheduling noise in this gate-specific assertion.
    suite["metrics"]["latency_ms"] = 100000
    demo.store.put("suites", suite["id"], suite, replace=True)
    candidate = demo.run_regression_suite("customer-support:v2", "support-gold:v1", suite["id"])
    assert candidate["gate"]["passed"]
    assert candidate["passed"]


def test_rejects_incompatible_baseline(demo):
    baseline = demo.run_regression_suite("customer-support:v1", "support-gold:v1")
    dataset = Dataset(name="other", version="v1", cases=[GoldCase(id="x", input="q", expected_output="a")])
    demo.create_dataset(dataset)
    with pytest.raises(ValueError, match="identical dataset"):
        demo.run_regression_suite("customer-support:v2", "other:v1", baseline["id"])


def test_gold_case_and_document_ids_are_unique():
    with pytest.raises(ValidationError):
        Dataset(name="d", version="v1", cases=[GoldCase(id="x", input="q")])
    c = GoldCase(id="x", input="q", expected_output="a")
    with pytest.raises(ValidationError):
        Dataset(name="d", version="v1", cases=[c, c])
    d = Document(id="x", text="x")
    with pytest.raises(ValidationError):
        AgentConfig(name="a", version="v1", documents=[d, d])


def test_failed_schema_blocks_suite(guard):
    guard.register_agent("schema", "v1", output_schema={"type": "object"})
    guard.create_dataset(
        Dataset(
            name="d",
            version="1",
            cases=[
                GoldCase(id="x", input="q", expected_output="I do not know based on the supplied evidence.")
            ],
        )
    )
    suite = guard.run_regression_suite("schema:v1", "d:1")
    assert not suite["passed"]
    assert suite["metrics"]["accuracy"] == 0


def test_ab_sticky_balanced_and_observed(demo):
    e = demo.ab_test("customer-support:v1", "customer-support:v2")
    a = demo.assign_experiment(e["id"], "subject-1")
    assert a == demo.assign_experiment(e["id"], "subject-1")
    assignments = [demo.assign_experiment(e["id"], str(i))["variant"] for i in range(1000)]
    assert 400 < assignments.count("a") < 600
    run = demo.execute_agent("Shipping", "customer-support:v1", experiment_id=e["id"], subject_id="subject-1")
    assert run["agent_id"] == a["agent_id"]
    result = demo.experiment_results(e["id"])
    assert result["results"][a["variant"]]["total_runs"] == 1
    with pytest.raises(ValueError):
        demo.execute_agent("Hi", "customer-support:v1", experiment_id=e["id"])


def test_judge_validates_live_scores_and_persists(guard):
    class Judge:
        def complete(self, *args):
            return Completion(
                json.dumps(
                    {
                        "correctness": 1,
                        "relevance": 0.8,
                        "safety": 1,
                        "completeness": 0.9,
                        "rationale": "Supported",
                    }
                ),
                input_tokens=50,
                output_tokens=20,
            )

    guard.provider = Judge()
    result = guard.llm_judge(
        "q",
        "a",
        "rubric",
        ModelSpec(provider="openai", model="judge", input_per_million=1, output_per_million=2),
    )
    assert result["scores"]["correctness"] == 1
    assert result["cost"] == pytest.approx(0.00009)
    assert guard.store.get("judgments", result["id"])["status"] == "success"
    with pytest.raises(ValueError, match="live provider"):
        guard.llm_judge("q", "a", "r", ModelSpec())


def test_judge_rejects_invalid_model_response(guard):
    class BadJudge:
        def complete(self, *args):
            return Completion('{"correctness": 100}')

    guard.provider = BadJudge()
    with pytest.raises(ValidationError):
        guard.llm_judge("q", "a", "r", ModelSpec(provider="openai", model="judge"))
    assert guard.store.list("judgments")[0]["status"] == "error"


@pytest.mark.parametrize(
    "provider,env,payload",
    [
        (
            "openai",
            "OPENAI_API_KEY",
            {
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        ),
        (
            "anthropic",
            "ANTHROPIC_API_KEY",
            {
                "content": [{"type": "text", "text": "answer"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        ),
        (
            "gemini",
            "GEMINI_API_KEY",
            {
                "candidates": [{"content": {"parts": [{"text": "answer"}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
            },
        ),
    ],
)
def test_provider_adapters(provider, env, payload, monkeypatch):
    monkeypatch.setenv(env, "test-only-not-a-credential")
    requests = []

    def respond(req):
        requests.append(json.loads(req.content))
        return httpx.Response(200, json=payload)

    spec = ModelSpec(provider=provider, model="test-model", input_per_million=1, output_per_million=2)
    result = ProviderClient(httpx.MockTransport(respond)).complete(
        spec,
        [{"role": "system", "content": "Be helpful"}, {"role": "user", "content": "Hi"}],
        ["lookup_order"],
    )
    assert result.text == "answer"
    assert result.input_tokens == 10 and result.output_tokens == 5
    assert cost_of(spec, result) == pytest.approx(0.00002)
    assert requests[0]["tools"]


@pytest.mark.parametrize("status,retryable", [(429, True), (503, True), (401, False), (400, False)])
def test_provider_errors_do_not_leak_bodies(status, retryable, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-credential")
    provider = ProviderClient(httpx.MockTransport(lambda req: httpx.Response(status, text="SECRET-RESPONSE")))
    with pytest.raises(ProviderError) as caught:
        provider.complete(ModelSpec(provider="openai", model="test"), [], [])
    assert caught.value.retryable == retryable
    assert "SECRET" not in str(caught.value)


def test_unknown_usage_is_not_free():
    spec = ModelSpec(provider="openai", model="test")
    assert cost_of(spec, Completion(input_tokens=100)) is None
    priced = ModelSpec(provider="openai", model="test", input_per_million=1, output_per_million=1)
    assert cost_of(priced, Completion(usage_known=False)) is None


def test_concurrent_writes(demo):
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(lambda i: demo.execute_agent("shipping", "customer-support:v1"), range(12)))
    assert len({r["id"] for r in runs}) == 12
    assert all(r["status"] == "success" for r in runs)


def test_api_end_to_end_and_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_API_TOKEN", "workspace-test-token")
    client = TestClient(create_app(str(tmp_path / "api.db")))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/agents").status_code == 401
    client.headers["Authorization"] = "Bearer workspace-test-token"
    assert client.post("/api/demo", json={}).status_code == 200
    assert len(client.get("/api/agents").json()) == 2
    run = client.post("/api/runs", json={"agent_id": "customer-support:v1", "input": "return item"})
    assert run.status_code == 201 and run.json()["status"] == "success"
    assert client.get("/api/runs/" + run.json()["id"]).status_code == 200
    assert client.get("/api/overview").json()["summary"]["total_runs"] == 1
    assert client.post("/api/runs", json={"agent_id": "missing", "input": "q"}).status_code == 404
    assert client.post("/api/runs", json={"agent_id": "x", "input": ""}).status_code == 422
    assert (
        client.post(
            "/api/agents", json={"name": "x", "version": "1", "output_schema": {"type": "nonsense"}}
        ).status_code
        == 422
    )
    assert client.get("/api/runs?limit=-1").status_code == 422


def test_cli_failure_is_nonzero(tmp_path):
    db = tmp_path / "ci.db"
    guard = AgentGuard(str(db))
    guard.register_agent("a", "1")
    guard.create_dataset(
        Dataset(name="d", version="1", cases=[GoldCase(id="x", input="q", expected_output="wrong")])
    )
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agentguard.cli",
            "--db",
            str(db),
            "suite",
            "--agent",
            "a:1",
            "--dataset",
            "d:1",
            "--output",
            str(report),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stderr
    assert json.loads(report.read_text())["passed"] is False


def test_remote_schema_refs_are_rejected(guard):
    with pytest.raises(ValueError, match="Only local"):
        guard.register_agent("remote", "v1", output_schema={"$ref": "http://127.0.0.1/private"})
    local = {"$defs": {"id": {"type": "integer"}}, "$ref": "#/$defs/id"}
    assert evaluate_schema("123", local)["passed"]


def test_500_gold_cases_supported(guard):
    guard.register_agent("bulk", "v1")
    cases = [
        GoldCase(id=str(i), input="xyzzy", expected_output="I do not know based on the supplied evidence.")
        for i in range(500)
    ]
    guard.create_dataset(Dataset(name="bulk", version="v1", cases=cases))
    result = guard.run_regression_suite("bulk:v1", "bulk:v1")
    assert len(result["cases"]) == 500
    assert result["passed"] and result["metrics"]["accuracy"] == 1
    with pytest.raises(ValidationError):
        Dataset(
            name="too-big", version="v1", cases=cases + [GoldCase(id="501", input="q", expected_output="a")]
        )


def test_timeout_fallback_cost_is_unknown(guard):
    class Timeout(ProviderClient):
        def complete(self, spec, *args):
            if spec.provider == "openai":
                raise ProviderError("openai transport failure", retryable=True)
            return super().complete(spec, *args)

    guard.provider = Timeout()
    guard.register_agent("timeout", "v1", ModelSpec(provider="openai", model="live"), fallbacks=[ModelSpec()])
    result = guard.execute_agent("q", "timeout:v1")
    assert result["status"] == "success" and result["cost"] is None


def test_tool_retrieval_is_used_as_evidence(guard):
    guard.register_agent(
        "tool-rag",
        "v1",
        tools=["knowledge_search"],
        retrieval=False,
        documents=[{"id": "doc", "text": "Shipping takes five days."}],
    )
    result = guard.execute_agent("Shipping", "tool-rag:v1")
    assert result["status"] == "success"
    assert result["retrieval"][0]["id"] == "doc"
    assert result["evaluation"]["faithfulness"]["score"] is not None


def test_run_judge_updates_experiment_quality(demo):
    experiment = demo.ab_test("customer-support:v1", "customer-support:v2")
    result = demo.execute_agent(
        "shipping", "customer-support:v1", experiment_id=experiment["id"], subject_id="s"
    )

    class Judge:
        def complete(self, *args):
            return Completion(
                json.dumps(
                    {
                        "correctness": 0.7,
                        "relevance": 0.8,
                        "safety": 1,
                        "completeness": 0.9,
                        "rationale": "Evidence checked",
                    }
                )
            )

    demo.provider = Judge()
    demo.judge_run(result["id"], ModelSpec(provider="openai", model="judge"))
    metrics = demo.experiment_results(experiment["id"])["results"][result["variant"]]
    assert metrics["judged_runs"] == 1
    assert metrics["judge_scores"]["correctness"] == 0.7


@pytest.mark.parametrize(
    "provider,env,payload",
    [
        (
            "openai",
            "OPENAI_API_KEY",
            {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]},
        ),
        (
            "anthropic",
            "ANTHROPIC_API_KEY",
            {"stop_reason": "max_tokens", "content": [{"type": "text", "text": "partial"}]},
        ),
        (
            "gemini",
            "GEMINI_API_KEY",
            {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "partial"}]}}]},
        ),
    ],
)
def test_truncated_answers_are_not_success(provider, env, payload, monkeypatch):
    monkeypatch.setenv(env, "test-only-not-a-credential")
    client = ProviderClient(httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    with pytest.raises(ProviderError):
        client.complete(ModelSpec(provider=provider, model="test"), [{"role": "user", "content": "q"}], [])


def test_otel_exports_nested_metadata_without_prompts(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from agentguard import tracing

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing.trace, "get_tracer", lambda name: provider.get_tracer(name))
    trace = tracing.RunTrace("test-run")
    with trace.span("agent.run"):
        with trace.span(
            "llm.generate", model="test-model", messages=[{"content": "private prompt"}]
        ) as attrs:
            attrs["input_tokens"] = 10
    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    assert spans[0].parent.span_id == spans[1].context.span_id
    assert spans[0].attributes["agentguard.input_tokens"] == 10
    assert "private prompt" not in str(spans[0].attributes)
    provider.shutdown()
