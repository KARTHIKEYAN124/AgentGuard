# AgentGuard

CI/CD for AI agents: register immutable versions, execute and trace them, evaluate gold datasets, and fail a release when quality, cost, or latency regresses.

**Hosted app:** https://agentguard-production-2392.up.railway.app - explore the public read-only demo, or create an email/password account for a private workspace. See [deployment details](docs/deployment.md).

This repository is a runnable multi-workspace reference implementation with real provider adapters and a deterministic offline provider. No provider credentials are included.

## Accounts and sharing

- Visitors can inspect sample traces and evaluations without an account.
- Sign up to get a private workspace with separate agent, trace, prompt, and evaluation storage.
- Open **Workspace & account** to create workspaces, invite teammates, change passwords, and view usage.
- Owners manage membership and limits; editors can run and modify agents; viewers have read-only access.
- Invitations are single-use links intended for a specific email address and expire after seven days. Share links privately; the app does not send invitation emails.
- Default daily allowances are 100 runs, 500 model calls, and $1 of reserved model budget. Live AI requires operator approval. Owners can lower limits; operators can raise them.
- Existing installation owners can sign up, then open **Workspace & account - Your account - Connect your original token-based workspace**, using the original `AGENTGUARD_API_TOKEN` from the ignored `.env.production` file. This grants access to preserved data and operator controls. Never share this token with visitors.

Authentication uses email/password, salted scrypt hashes, and expiring HttpOnly sessions. Google OAuth, email verification, and forgotten-password email recovery are not implemented. Keep passwords in a password manager.

## Run locally

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js 20.19+ or 22.12+.

```powershell
uv sync --group dev
cd frontend
npm ci
npm run build
cd ..
uv run python main.py
```

Open **http://127.0.0.1:8000**. Interactive API docs: **http://127.0.0.1:8000/docs**.

For hosting on a real server, see [Server deployment](docs/deployment.md). A multi-stage `Dockerfile` and Railway health-check configuration are included; persistent `/data` storage and a workspace API token are required.

1. Create an account, then click **Load demo workspace**. This creates two agent versions, two prompt versions, and five gold cases. It does not fabricate metrics.
2. Click **Execute agent** to inspect an input/output, routing decisions, retrieval, model calls, tools, memory, evaluations, and nested spans.
3. Click **Run evaluation** to create a baseline, then run the candidate with that suite selected under **Compare against**.
4. Create an **Experiment**, choose it in **Execute agent**, and supply a stable subject ID. Inspect the per-variant results.

Development UI: run `npm run dev` inside `frontend/` while the Python server runs on port 8000. Vite proxies `/api` to the backend.

## Requirements mapped to implementation

| Function | Implementation / behavior |
| --- | --- |
| `register_agent(name, version, model)` | `AgentGuard.register_agent`: immutable definitions, provider/model, pricing, reasoning model, fallbacks, tools, documents, prompt version, memory, output schema |
| `execute_agent(input, agent_config)` | `AgentGuard.execute_agent`: retrieval, routing, LLM → allowlisted tool loop → final answer; optional bounded session history |
| `route_model(task)` | `AgentGuard.route_model(task, config)`: extraction uses default model, reasoning uses reasoning model; automatic classification is a documented string/length heuristic |
| Provider outage fallback | Retryable transport failures, HTTP 408/429 and 5xx try the next configured provider; 4xx configuration/auth failures fail immediately. Never silently switch to demo unless explicitly in the fallback list |
| `trace_run()` | `AgentGuard.trace_run(run_id)`: persisted inputs, prompts, output, errors, tools, retrieval, tokens, cost and duration; nested OpenTelemetry spans |
| `evaluate_schema(output)` | Strict Pydantic model validation through Python or JSON Schema Draft 2020-12 through the API |
| `evaluate_faithfulness(answer, sources)` | Explicitly labeled lexical screening; live `llm_judge` includes a semantic faithfulness score and rationale |
| `evaluate_retrieval(query, expected_docs)` | Precision@k, recall@k and truncated MRR from a supplied ranked list; duplicate IDs removed; k remains the precision denominator |
| `llm_judge(input, response, rubric)` | OpenAI / Anthropic / Gemini evaluation with validated 0–1 correctness, relevance, safety, completeness, optional faithfulness, rationale, token usage and cost |
| `run_regression_suite(agent_version)` | Up to 500 gold cases; normalized exact match, schema, expected tools, retrieval metrics, optional live judge; stored agent/dataset snapshots and dataset hash |
| `detect_regression(current, baseline)` | Blocks for accuracy loss **>3 percentage points**, mean cost increase **>20%**, or mean latency increase **>30%**. Exact thresholds pass |
| `prompt_version()` | Immutable templates, resolved into registered agent definitions; evaluation suites retain prompt IDs and snapshot |
| `ab_test(agent_a, agent_b)` | Default 50/50 sticky hash assignment by experiment + subject; per-variant run count, execution success, mean/p95 latency and cost |
| Dashboard | Overview, registry, trace search/filter/inspector, suites, gold datasets, reports, prompt history, A/B results |

## Python API

```python
from agentguard import AgentGuard, evaluate_schema
from agentguard.models import ModelSpec
from pydantic import BaseModel

guard = AgentGuard("data/agentguard.db")
guard.prompt_version("support", "v3", "Answer using evidence. Admit missing information.")
agent = guard.register_agent(
    "support",
    "v3",
    ModelSpec(provider="demo", model="demo-grounded"),
    prompt_id="support:v3",
    documents=[{"id": "returns", "text": "Returns are accepted within 30 days."}],
    retrieval=True,
    tools=["lookup_order"],
    memory=True,
)
run = guard.execute_agent("When can I return an order?", agent["id"], session_id="customer-123")
trace = guard.trace_run(run["id"])


class Customer(BaseModel):
    customer_id: int


assert evaluate_schema('{"customer_id":123}', Customer)["passed"]
```

For live agents, set `model.provider` to `openai`, `anthropic` or `gemini` and `model.model` to an enabled model ID in your account. Configure `input_per_million` and `output_per_million` from that model's current USD price schedule. A model can also be assigned to `reasoning_model` or the ordered `fallbacks` array. Model IDs and prices are intentionally not hardcoded: availability and rates vary over time and account.

OpenAI key provisioning was requested through Codex's secure Platform picker; that workflow still needs its confirmed project selection. No key has been created or written by this implementation. Complete that secure flow to enable OpenAI; never paste a key into chat. The app reads `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY` from its environment, and loads `.env.local` when launched via `main.py` or the CLI. All env files are ignored. Provider readiness in the dashboard checks presence, not validity or billing status.

`lookup_order` is an explicitly labeled demo fixture (order `123` is shipped). Integrate a real authenticated CRM/order client in the allowlisted tool branch before using it with customers. `knowledge_search` searches the registered document snapshot using token overlap; replace ranking with an indexed/vector retriever for large corpora. Tools are not shell execution.

## API endpoints

All data endpoints are under `/api`. Lists support `limit` (1–1000) and `offset`; the UI shows the latest 200 records.

| Endpoint | Purpose |
| --- | --- |
| `POST /agents`, `GET /agents`, `GET /agents/{id}` | Registry |
| `POST /agents/{id}/route?task=reasoning` | Inspect routing candidates |
| `POST /runs`, `GET /runs/{id}` | Execute; inspect complete trace |
| `DELETE /agents/{id}/memory/{session_id}` | Clear that version's session memory |
| `POST /prompts`, `GET /prompts/{id}/results` | Version a prompt; inspect linked suite evidence |
| `POST /datasets`, `GET /datasets` | Immutable gold data |
| `POST /suites`, `GET /suites/{id}` | Run and retrieve regression reports |
| `POST /evaluations/schema` | `{output, json_schema}` |
| `POST /evaluations/faithfulness` | `{answer, sources}` |
| `POST /evaluations/retrieval` | `{query, expected_docs, retrieved_docs, k}` |
| `POST /evaluations/judge` | `{input, response, rubric, sources, model}` |
| `POST /runs/{id}/judge` | `{model, rubric}`; attach quality scores to a recorded run and its A/B variant |
| `POST /evaluations/regression` | `{current, baseline}` with accuracy, cost, latency_ms |
| `POST /experiments`, `GET /experiments/{id}/results` | Create and compare A/B variants |

For experiment traffic, send `experiment_id` and `subject_id` in `POST /runs`; the assigned variant overrides `agent_id`. The hash is stable for the experiment and does not store the subject ID in the run. Session IDs are a separate caller responsibility.

## CI deployment gate

```powershell
uv run python -m agentguard.cli demo
uv run python -m agentguard.cli suite --agent customer-support:v1 --dataset support-gold:v1 --output data/baseline.json
uv run python -m agentguard.cli suite --agent customer-support:v2 --dataset support-gold:v1 --baseline-file data/baseline.json --output data/candidate.json
```

Exit codes: **0** passed, **1** failed evaluation/gate, **2** configuration/input failure. Deploy only after a successful command. The included GitHub Actions workflow verifies the deterministic baseline and uploads its report. Add your actual deployment step with `needs: evaluate`; a failed job blocks it. The tool cannot block a deployment pipeline that does not invoke it.

Use `register path/to/agent.json` and `dataset path/to/gold.json` to import custom definitions. Preserve the baseline report as a trusted CI artifact, and use `--baseline-file` in a clean CI database. Baselines must be completed and have the identical dataset hash and evaluator configuration. Without a baseline all gold cases must pass. With one, relative gates apply; runtime failures always fail the suite.

Costs are **USD token-cost estimates**, not invoice totals. Unknown pricing/usage blocks the cost gate. A positive increase from a zero baseline also blocks; zero-to-zero passes. Judge costs are recorded separately and are not added to agent-runtime cost. Cached Anthropic/Gemini usage reports unknown cost because separate cache rates are not modeled. Demo cost is zero and its token counts are estimates. Latency includes retrieval, tools, evaluation screening, and persistence during the run. Do not use tiny deterministic-demo timings as a production performance baseline: scheduling noise can trigger the latency gate.

Accuracy is normalized case-insensitive whitespace-collapsed exact match plus configured schema and expected-tool checks; it is not a semantic accuracy claim. Retrieval metrics and judge scores are additional evidence rather than silently changing the release policy. Empty relevance sets yield null recall/MRR. Faithfulness without sources is null. LLM judges are fallible and require calibration, especially on adversarial input. A/B output is descriptive and does not claim statistical significance or equate execution success with answer correctness.

## OpenTelemetry and Langfuse

Nested spans are always saved in SQLite. To export standard OpenTelemetry over HTTP, configure `OTEL_EXPORTER_OTLP_ENDPOINT` (collector base URL) or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` (full traces endpoint), with optional `OTEL_EXPORTER_OTLP_HEADERS`.

For Langfuse's OpenTelemetry ingestion, point `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to your regional/self-hosted Langfuse `/api/public/otel/v1/traces` endpoint and set its required Basic authorization header through `OTEL_EXPORTER_OTLP_HEADERS`. See the [Langfuse OpenTelemetry integration](https://langfuse.com/integrations/native/opentelemetry) for the current region and authentication details. No Langfuse-specific SDK is required for generic spans.

Only metadata (run ID, span name, status, model, provider, token usage, and known cost) is exported by default. Full prompt/output/tool payloads stay in the local trace store. Exported spans are generic OTel spans, not a claim of Langfuse-specific generation/cost dashboards. The exporter batches asynchronously and flushes on graceful shutdown.

## Operational boundaries

- Default binding is loopback. Hosting requires `AGENTGUARD_API_TOKEN` for legacy API access and operator migration. Browser users authenticate with session cookies and select a private workspace using `X-Workspace-Id`. Public sample reads use `X-AgentGuard-Demo: true`; mutations are rejected. Set `AGENTGUARD_PUBLIC_URL` to the HTTPS origin for Secure cookies and origin checks.
- SQLite uses WAL, transactional writes, immutable definition IDs, and parameterized queries. Back up the database and its WAL consistently. For multi-replica/high-volume workloads, migrate to Postgres and a durable worker queue.
- Suite execution is synchronous in a FastAPI thread worker or CLI. Progress is persisted case by case, but process interruption is not automatically resumed. In CI, rerun interrupted suites; a `running` suite cannot be a baseline.
- The server stores raw evaluation inputs, outputs, and session memory. Use synthetic/approved data, access controls and retention appropriate to your environment. Session history is capped at ten exchanges. Concurrent requests in the same session do not guarantee ordering.
- Provider requests have 60-second operation timeouts and 10-second connection timeouts. Agent steps are capped at ten and tool calls at eight per step. There is no custom executable-code tool, arbitrary provider URL, or hidden fallback to a free model.
- No live provider or hosted Langfuse smoke test has been performed without credentials. Adapters are tested against mocked provider protocols; verify the configured model's tool/JSON behavior and pricing in your account before rollout.

## Verify

```powershell
uv run pytest -q
uv run ruff check .
cd frontend
npm run build
npx playwright install chromium
npm run test:e2e
```

The browser tests use an isolated temporary database and start a server on port 8011. They cover setup, execution, trace inspection, evaluation, report export, experiments, and mobile overflow. Backend tests cover schema strictness, metric boundaries, provider protocols, outages, memory isolation, immutable versions, bad tools, concurrent writes, baseline compatibility, API authorization, and CI failure codes.

### Live AI spending controls

For hosted workspace APIs, configure provider secrets and an operator-owned `AGENTGUARD_MODEL_PRICES` JSON catalog, keyed by `provider/model`, with `input_per_million` and `output_per_million` USD rates. Enable live access per workspace under operator controls. User-supplied model rates must match the catalog.

Model calls reserve a conservative token budget before execution. Failed calls also consume reservations; this is a spending guard, not a billing invoice. The Python SDK and CLI are trusted local interfaces and do not apply workspace quotas. All workspace SQLite files, the accounts database, and the public sample database reside under the persistent data directory; back up the entire directory consistently. Single-replica deployment remains required.
