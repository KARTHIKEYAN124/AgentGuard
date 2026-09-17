import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Bot,
  FlaskConical,
  GitBranch,
  KeyRound,
  LayoutDashboard,
  Menu,
  RefreshCw,
  ShieldCheck,
  TextCursorInput,
  X,
} from "lucide-react";
import { api, date, percent } from "./api";
import { Empty, Json, Modal, Status, TraceTable } from "./components";
import Overview from "./Overview";
import {
  ExecuteForm,
  ExperimentDetail,
  ExperimentForm,
  JsonCreate,
  SuiteDetail,
  SuiteForm,
  TraceDetail,
} from "./Details";

const pages = [
  ["Overview", LayoutDashboard],
  ["Agents", Bot],
  ["Traces", Activity],
  ["Evaluations", FlaskConical],
  ["Prompts", TextCursorInput],
  ["Experiments", GitBranch],
];
const agentTemplate = {
  name: "my-agent",
  version: "v1",
  model: { provider: "demo", model: "demo-grounded" },
  system_prompt:
    "Answer using supplied evidence. If evidence is missing, say you do not know.",
  retrieval: true,
  documents: [
    { id: "policy", text: "Unused items can be returned within 30 days." },
  ],
  tools: [],
  memory: false,
  max_steps: 5,
};
const datasetTemplate = {
  name: "my-gold",
  version: "v1",
  cases: [
    {
      id: "return-policy",
      input: "Can I return unused items?",
      expected_output: "Unused items can be returned within 30 days.",
      expected_docs: ["policy"],
    },
  ],
};

export default function App({
  access,
  onLogin,
  onSettings,
  onWorkspaceChange,
  onLogout,
}) {
  const [page, setPage] = useState("Overview");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [modal, assignModal] = useState(null);
  const [mobile, setMobile] = useState(false);
  const [filter, setFilter] = useState("");
  const [status, setStatus] = useState("all");
  const canEdit = !access.isDemo && ["owner", "editor"].includes(access.role);
  function setModal(value) {
    if (
      value &&
      ["execute", "suite", "json", "experiment"].includes(value.type) &&
      !canEdit
    ) {
      if (!access.user) onLogin();
      else if (access.isDemo)
        onWorkspaceChange(access.workspaces[0]?.id || "demo");
      else
        setError(
          "Your viewer role is read-only. Ask an owner for editor access.",
        );
      return;
    }
    assignModal(value);
  }
  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const names = [
        "overview",
        "agents",
        "runs",
        "datasets",
        "suites",
        "prompts",
        "experiments",
        "providers",
      ];
      const responses = await Promise.allSettled(names.map((n) => api(n)));
      const failed = responses.find((r) => r.status === "rejected");
      if (failed) throw failed.reason;
      setData(Object.fromEntries(names.map((n, i) => [n, responses[i].value])));
      setError("");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    refresh();
  }, [refresh]);
  const close = () => setModal(null);
  const created = () => {
    close();
    refresh();
  };
  const trace = (run) => setModal({ type: "trace", run });
  const run = () => setModal({ type: "execute" });
  const suite = () => setModal({ type: "suite" });
  const seed = async () => {
    if (!canEdit) {
      if (!access.user) onLogin();
      else setError("Switch to an editable workspace first.");
      return;
    }
    setBusy(true);
    try {
      await api("demo", {});
      await refresh();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };
  const heading = (title, subtitle, action, label) => (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      {action && (
        <button className="primary" onClick={action}>
          {label}
        </button>
      )}
    </div>
  );
  return (
    <div className="app">
      <aside className={mobile ? "open" : ""}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("Overview");
          }}
        >
          <ShieldCheck size={26} />
          <span>AgentGuard</span>
        </a>
        <div className="workspace">
          <span className="workspace-avatar">AG</span>
          <div>
            {access.user ? (
              <select
                aria-label="Active workspace"
                value={access.workspaceId}
                onChange={(e) => onWorkspaceChange(e.target.value)}
              >
                <option value="demo">Public demo</option>
                {access.workspaces.map((w) => (
                  <option value={w.id} key={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            ) : (
              "Public demo"
            )}
            <small>
              {access.isDemo
                ? "Read-only sample workspace"
                : `${access.role} · Private workspace`}
            </small>
          </div>
        </div>
        <nav aria-label="Main navigation">
          {pages.map(([name, Icon]) => (
            <button
              key={name}
              className={page === name ? "active" : ""}
              onClick={() => {
                setPage(name);
                setMobile(false);
              }}
            >
              <Icon size={18} />
              {name}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-note">
            <ShieldCheck size={19} />
            <strong>Ship with evidence.</strong>
            <p>
              Trace every action.
              <br />
              Catch regressions before release.
            </p>
          </div>
          <button onClick={access.user ? onSettings : onLogin}>
            <KeyRound size={16} />{" "}
            {access.user ? "Workspace & account" : "Sign in / Create account"}
          </button>
          <a href="/docs" target="_blank" rel="noreferrer">
            API documentation ↗
          </a>
          <small>AgentGuard / v0.2.0</small>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <button
              className="icon mobile-toggle"
              aria-label="Toggle navigation"
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X size={20} /> : <Menu size={20} />}
            </button>
            <span className="muted">Workspace</span>
            <span className="slash">/</span>
            <span>{page}</span>
          </div>
          <div>
            <span className="connection">
              <span className={`dot ${error ? "offline" : ""}`} />
              {error
                ? "Connection issue"
                : access.isDemo
                  ? "Public demo"
                  : "Private workspace"}
            </span>
            <button
              className="icon"
              aria-label="Refresh workspace"
              disabled={busy}
              onClick={refresh}
            >
              <RefreshCw size={16} className={busy ? "spin" : ""} />
            </button>
            <button
              className="account-action"
              onClick={access.user ? onLogout : onLogin}
            >
              {access.user ? "Sign out" : "Sign in"}
            </button>
          </div>
        </header>
        <main>
          {error && (
            <div className="error" role="alert">
              {error}{" "}
              <button
                className="text-button"
                onClick={access.user ? onSettings : onLogin}
              >
                {access.user ? "Workspace settings" : "Sign in"}
              </button>
            </div>
          )}
          {access.isDemo && (
            <div className="public-banner">
              <div>
                <strong>Explore AgentGuard</strong>
                <p>
                  This read-only demo uses sample agents and real deterministic
                  evaluation runs. Your own workspace stays private.
                </p>
              </div>
              <button
                className="primary"
                onClick={access.user ? onSettings : onLogin}
              >
                {access.user
                  ? "Manage your workspaces"
                  : "Create your workspace"}
              </button>
            </div>
          )}
          {!access.isDemo && access.role === "viewer" && (
            <p className="demo-note viewer-note">
              Viewer access · You can inspect and export results. An owner can
              grant editing access.
            </p>
          )}
          {page === "Overview" && (
            <Overview
              overview={data?.overview}
              onRun={run}
              onSuite={suite}
              onTrace={trace}
              onSeed={seed}
              busy={busy}
            />
          )}
          {page === "Agents" && (
            <>
              {heading(
                "Agent registry",
                "Immutable definitions. Reproducible behavior.",
                () =>
                  setModal({
                    type: "json",
                    title: "Register agent",
                    endpoint: "agents",
                    initial: data?.providers?.ollama ? {
                      ...agentTemplate,
                      name: "local-assistant",
                      model: { provider: "ollama", model: "qwen2.5:1.5b" },
                      system_prompt: "Answer the user's question directly and concisely. Admit uncertainty. Do not invent company policies. When supplied evidence exists, use it for company-specific answers.",
                      documents: [],
                      retrieval: false,
                      memory: true,
                    } : agentTemplate,
                  }),
                "Register agent",
              )}
              <div className="provider-strip">
                {Object.entries(data?.providers || {}).map(([p, ready]) => (
                  <span key={p}>
                    <span className={`dot ${!ready ? "disabled" : ""}`} />
                    {p}
                    <small>{ready ? "Configured" : "Not configured"}</small>
                  </span>
                ))}
              </div>
              <section className="panel">
                {!data?.agents.length ? (
                  <Empty>
                    No agents registered. Load the demo from Overview or
                    register your own.
                  </Empty>
                ) : (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Agent / version</th>
                          <th>Provider / model</th>
                          <th>Capabilities</th>
                          <th>Prompt</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {data.agents.map((a) => (
                          <tr key={a.id}>
                            <td>
                              <strong>{a.name}</strong>
                              <small className="mono">{a.version}</small>
                            </td>
                            <td>
                              {a.model.provider}
                              <small className="mono">{a.model.model}</small>
                            </td>
                            <td>
                              {[
                                a.retrieval && "Retrieval",
                                a.memory && "Memory",
                                ...a.tools,
                              ]
                                .filter(Boolean)
                                .join(" · ") || "LLM only"}
                            </td>
                            <td>{a.prompt_id || "Inline prompt"}</td>
                            <td>
                              <button
                                onClick={() =>
                                  setModal({
                                    type: "inspect",
                                    title: a.id,
                                    value: a,
                                  })
                                }
                              >
                                Inspect
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
              <p className="muted footnote">
                Model rates are configured per million tokens in USD. Unpriced
                live runs report unknown cost. CRM order lookup uses a labeled
                local fixture.
              </p>
            </>
          )}
          {page === "Traces" && (
            <>
              {heading(
                "Run traces",
                "Follow a request from input to final result.",
                run,
                "Execute agent",
              )}
              <div className="toolbar">
                <input
                  aria-label="Search traces"
                  placeholder="Search agent, model, or run ID…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <select
                  aria-label="Filter trace status"
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                >
                  <option value="all">All statuses</option>
                  <option value="success">Success</option>
                  <option value="error">Error</option>
                  <option value="running">Running</option>
                </select>
                <span className="muted">Latest 200 runs</span>
              </div>
              <section className="panel">
                <TraceTable
                  runs={(data?.runs || []).filter(
                    (r) =>
                      (status === "all" || r.status === status) &&
                      `${r.id} ${r.agent_id} ${r.model}`
                        .toLowerCase()
                        .includes(filter.toLowerCase()),
                  )}
                  onSelect={trace}
                />
              </section>
            </>
          )}
          {page === "Evaluations" && (
            <>
              {heading(
                "Evaluation suites",
                "Compare versions against the same gold dataset.",
                suite,
                "Run evaluation",
              )}
              <section className="panel">
                <div className="panel-heading">
                  <h2>Suite history</h2>
                  <span className="muted">Accuracy · cost · latency gates</span>
                </div>
                {!data?.suites.length ? (
                  <Empty>
                    No suites yet. Run your first baseline to establish a
                    quality checkpoint.
                  </Empty>
                ) : (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Agent</th>
                          <th>Dataset</th>
                          <th>Accuracy</th>
                          <th>Gate</th>
                          <th>Created</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {data.suites.map((s) => (
                          <tr key={s.id}>
                            <td>
                              {s.agent_id}
                              <small className="mono">{s.id.slice(0, 8)}</small>
                            </td>
                            <td>{s.dataset_id}</td>
                            <td>{percent(s.metrics?.accuracy)}</td>
                            <td>
                              <Status
                                value={
                                  s.status === "running"
                                    ? "running"
                                    : s.passed
                                      ? "passed"
                                      : "blocked"
                                }
                              />
                            </td>
                            <td>{date(s.created_at)}</td>
                            <td>
                              <button
                                onClick={() =>
                                  setModal({ type: "report", suite: s })
                                }
                              >
                                Report
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
              <section className="panel section-gap">
                <div className="panel-heading">
                  <h2>Gold datasets</h2>
                  <button
                    onClick={() =>
                      setModal({
                        type: "json",
                        title: "Create gold dataset",
                        endpoint: "datasets",
                        initial: datasetTemplate,
                      })
                    }
                  >
                    Create dataset
                  </button>
                </div>
                {!data?.datasets.length ? (
                  <Empty>
                    Add up to 500 cases per version, with expected answers or
                    output schemas.
                  </Empty>
                ) : (
                  data.datasets.map((d) => (
                    <div className="list-row" key={d.id}>
                      <div>
                        <strong>{d.id}</strong>
                        <small>
                          {d.cases.length} gold cases · SHA-256{" "}
                          {d.digest.slice(0, 12)}
                        </small>
                      </div>
                      <button
                        onClick={() =>
                          setModal({ type: "inspect", title: d.id, value: d })
                        }
                      >
                        Inspect
                      </button>
                    </div>
                  ))
                )}
              </section>
              <p className="muted footnote">
                Faithfulness screening uses lexical overlap. Semantic LLM
                judging is available through POST /api/evaluations/judge and
                optional suite judge_model configuration.
              </p>
            </>
          )}
          {page === "Prompts" && (
            <>
              {heading(
                "Prompt versions",
                "Keep prompts and their evaluation evidence together.",
                () =>
                  setModal({
                    type: "json",
                    title: "Create prompt version",
                    endpoint: "prompts",
                    initial: {
                      name: "support",
                      version: "v3",
                      template:
                        "Answer using supplied evidence. If evidence is missing, say you do not know.",
                    },
                  }),
                "Create version",
              )}
              <section className="panel">
                {!data?.prompts.length ? (
                  <Empty>
                    No prompt versions yet. Create one and reference its ID when
                    registering an agent.
                  </Empty>
                ) : (
                  data.prompts.map((p) => (
                    <div className="prompt-row" key={p.id}>
                      <div>
                        <h3>
                          {p.name}{" "}
                          <span className="muted mono">{p.version}</span>
                        </h3>
                        <p className="payload">{p.template}</p>
                        <small>{date(p.created_at)}</small>
                      </div>
                      <button
                        onClick={async () => {
                          try {
                            const value = await api(
                              `prompts/${encodeURIComponent(p.id)}/results`,
                            );
                            setModal({
                              type: "inspect",
                              title: `${p.id} · evaluation evidence`,
                              value,
                            });
                          } catch (e) {
                            setError(e.message);
                          }
                        }}
                      >
                        View evaluations
                      </button>
                    </div>
                  ))
                )}
              </section>
            </>
          )}
          {page === "Experiments" && (
            <>
              {heading(
                "A/B experiments",
                "Stable traffic splits. Observable production performance.",
                () => setModal({ type: "experiment" }),
                "Create experiment",
              )}
              <section className="panel">
                {!data?.experiments.length ? (
                  <Empty>
                    No experiments yet. Compare two registered agent versions
                    with a stable traffic split.
                  </Empty>
                ) : (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Experiment</th>
                          <th>Agent A</th>
                          <th>Agent B</th>
                          <th>Split</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {data.experiments.map((e) => (
                          <tr key={e.id}>
                            <td>
                              {e.name}
                              <small className="mono">{e.id.slice(0, 8)}</small>
                            </td>
                            <td>{e.agent_a}</td>
                            <td>{e.agent_b}</td>
                            <td>
                              {Math.round(e.allocation_a * 100)} /{" "}
                              {Math.round((1 - e.allocation_a) * 100)}
                            </td>
                            <td>
                              <button
                                onClick={async () => {
                                  try {
                                    setModal({
                                      type: "experiment-results",
                                      value: await api(
                                        `experiments/${e.id}/results`,
                                      ),
                                    });
                                  } catch (err) {
                                    setError(err.message);
                                  }
                                }}
                              >
                                Results
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
        </main>
        <footer>
          <span>AgentGuard</span>
          <span>Evaluation is a release requirement.</span>
        </footer>
      </div>
      {modal?.type === "execute" && (
        <ExecuteForm
          agents={data?.agents || []}
          experiments={data?.experiments || []}
          onClose={close}
          onResult={(r) => {
            trace(r);
            refresh();
          }}
        />
      )}
      {modal?.type === "suite" && (
        <SuiteForm
          agents={data?.agents || []}
          datasets={data?.datasets || []}
          suites={data?.suites || []}
          onClose={close}
          onResult={(s) => {
            setModal({ type: "report", suite: s });
            refresh();
          }}
        />
      )}
      {modal?.type === "trace" && (
        <TraceDetail run={modal.run} onClose={close} />
      )}
      {modal?.type === "report" && (
        <SuiteDetail suite={modal.suite} onClose={close} onTrace={trace} />
      )}
      {modal?.type === "json" && (
        <JsonCreate {...modal} onClose={close} onCreated={created} />
      )}
      {modal?.type === "inspect" && (
        <Modal title={modal.title} onClose={close} wide>
          <Json value={modal.value} />
        </Modal>
      )}
      {modal?.type === "experiment" && (
        <ExperimentForm
          agents={data?.agents || []}
          onClose={close}
          onCreated={created}
        />
      )}
      {modal?.type === "experiment-results" && (
        <ExperimentDetail value={modal.value} onClose={close} />
      )}
    </div>
  );
}
