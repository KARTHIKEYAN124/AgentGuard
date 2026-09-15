import { useState } from "react";
import { api, date, money, latency, percent } from "./api";
import { Empty, Field, Gate, Json, Modal, Status } from "./components";

export function TraceDetail({ run, onClose }) {
  const [selected, setSelected] = useState(null);
  return (
    <Modal title={`Trace ${run.id.slice(0, 8)}`} onClose={onClose} wide>
      <div className="detail-summary">
        <Status value={run.status} />
        <span>{run.agent_id}</span>
        <span>{latency(run.latency_ms)}</span>
        <span>{money(run.cost)}</span>
        <span>
          {run.tokens.input + run.tokens.output} tokens
          {run.usage_estimated ? " (estimated)" : ""}
        </span>
      </div>
      {run.error && <p className="error">{run.error}</p>}
      <div className="io-grid">
        <section>
          <h3>Input</h3>
          <p className="payload">{run.input}</p>
        </section>
        <section>
          <h3>Output</h3>
          <p className="payload">{run.output || "No final output"}</p>
        </section>
      </div>
      <h3>Execution timeline</h3>
      <div className="timeline">
        {run.spans.map((s) => (
          <button
            className={`span-row ${selected?.id === s.id ? "selected" : ""}`}
            key={s.id}
            onClick={() => setSelected(s)}
          >
            <span
              className="mono"
              style={{ paddingLeft: s.parent_id ? 16 : 0 }}
            >
              {s.name}
            </span>
            <span className="span-track">
              <i
                style={{
                  width: `${Math.max(2, Math.min(100, (s.latency_ms / Math.max(run.latency_ms, 1)) * 100))}%`,
                  background: s.status === "error" ? "#ce5555" : undefined,
                }}
              />
            </span>
            <span>{latency(s.latency_ms)}</span>
          </button>
        ))}
      </div>
      {selected && (
        <>
          <h3>{selected.name}</h3>
          <Json value={selected} />
        </>
      )}
      <h3>Evaluations</h3>
      <Json value={run.evaluation} />
    </Modal>
  );
}

export function SuiteDetail({ suite, onClose, onTrace }) {
  const [error, setError] = useState("");
  return (
    <Modal title={`Evaluation · ${suite.agent_id}`} onClose={onClose} wide>
      <p className="muted">
        {suite.dataset_id} · {date(suite.created_at)}
      </p>
      <Gate suite={suite} />
      {suite.metrics && (
        <div className="detail-summary">
          <span>Accuracy {percent(suite.metrics.accuracy)}</span>
          <span>Mean cost {money(suite.metrics.cost)}</span>
          <span>Mean latency {latency(suite.metrics.latency_ms)}</span>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Gold case</th>
              <th>Result</th>
              <th>Trace</th>
              <th>Checks</th>
            </tr>
          </thead>
          <tbody>
            {suite.cases.map((c) => (
              <tr key={c.case_id}>
                <td>{c.case_id}</td>
                <td>
                  <Status value={c.passed ? "passed" : "failed"} />
                </td>
                <td>
                  <button
                    className="text-button mono"
                    onClick={async () => {
                      try {
                        onTrace(await api("runs/" + c.run_id));
                      } catch (e) {
                        setError(e.message);
                      }
                    }}
                  >
                    {c.run_id.slice(0, 8)}
                  </button>
                </td>
                <td>
                  <details>
                    <summary>Inspect</summary>
                    <Json value={c.checks} />
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="modal-actions">
        <button
          onClick={() => {
            const url = URL.createObjectURL(
              new Blob([JSON.stringify(suite, null, 2)], {
                type: "application/json",
              }),
            );
            const a = document.createElement("a");
            a.href = url;
            a.download = `agentguard-${suite.id}.json`;
            a.click();
            URL.revokeObjectURL(url);
          }}
        >
          Export report
        </button>
      </div>
    </Modal>
  );
}

export function ExecuteForm({ agents, experiments, onClose, onResult }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title="Execute agent" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          const f = new FormData(e.target);
          try {
            const result = await api("runs", {
              agent_id: f.get("agent_id"),
              input: f.get("input"),
              task: f.get("task"),
              session_id: f.get("session_id") || null,
              experiment_id: f.get("experiment_id") || null,
              subject_id: f.get("subject_id") || null,
            });
            onResult(result);
          } catch (err) {
            setError(err.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="Agent version">
          <select name="agent_id" required>
            {agents.map((a) => (
              <option key={a.id}>{a.id}</option>
            ))}
          </select>
        </Field>
        <Field label="Input">
          <textarea
            name="input"
            defaultValue="Can I return an unused item?"
            required
            rows={4}
          />
        </Field>
        <Field label="Routing policy">
          <select name="task">
            <option value="auto">Automatic</option>
            <option value="extraction">Simple extraction</option>
            <option value="reasoning">Complex reasoning</option>
          </select>
        </Field>
        <Field
          label="Session ID"
          hint="Optional. Memory is isolated by agent version and session."
        >
          <input name="session_id" placeholder="customer-session-001" />
        </Field>
        <details>
          <summary>A/B experiment routing</summary>
          <Field
            label="Experiment"
            hint="Overrides the agent selection using a stable assignment."
          >
            <select name="experiment_id">
              <option value="">No experiment</option>
              {experiments.map((e) => (
                <option value={e.id} key={e.id}>
                  {e.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Subject ID">
            <input name="subject_id" placeholder="Required for experiments" />
          </Field>
        </details>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={busy || !agents.length}>
            {busy ? "Executing…" : "Execute & trace"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function SuiteForm({ agents, datasets, suites, onClose, onResult }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dataset, setDataset] = useState(datasets[0]?.id || "");
  return (
    <Modal title="Run evaluation" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          const f = new FormData(e.target);
          try {
            onResult(
              await api("suites", {
                agent_id: f.get("agent_id"),
                dataset_id: dataset,
                baseline_id: f.get("baseline_id") || null,
              }),
            );
          } catch (err) {
            setError(err.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="Agent version">
          <select name="agent_id" required>
            {agents.map((a) => (
              <option key={a.id}>{a.id}</option>
            ))}
          </select>
        </Field>
        <Field label="Gold dataset">
          <select
            value={dataset}
            onChange={(e) => setDataset(e.target.value)}
            required
          >
            {datasets.map((d) => (
              <option key={d.id}>{d.id}</option>
            ))}
          </select>
        </Field>
        <Field
          label="Compare against"
          hint="Only suites from the identical dataset can be used as a baseline."
        >
          <select name="baseline_id" key={dataset}>
            <option value="">Create baseline · no comparison</option>
            {suites
              .filter(
                (s) => s.dataset_id === dataset && s.status === "completed",
              )
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.agent_id} · {s.id.slice(0, 8)}
                </option>
              ))}
          </select>
        </Field>
        <p className="muted">
          Runs each gold case with isolated memory. Live providers may incur
          charges. Keep this dialog open while the suite executes.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="primary"
            disabled={busy || !agents.length || !datasets.length}
          >
            {busy ? "Evaluating…" : "Run suite"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function JsonCreate({ title, initial, endpoint, onClose, onCreated }) {
  const [value, setValue] = useState(JSON.stringify(initial, null, 2));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose} wide>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          try {
            await api(endpoint, JSON.parse(value));
            onCreated();
          } catch (err) {
            setError(err.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field
          label="Definition · JSON"
          hint="Versions are immutable. Save changes under a new version."
        >
          <textarea
            className="code-editor"
            rows={20}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            spellCheck={false}
          />
        </Field>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={busy}>
            {busy ? "Saving…" : "Save definition"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function ExperimentForm({ agents, onClose, onCreated }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title="Create experiment" onClose={onClose}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          const f = new FormData(e.target);
          try {
            await api("experiments", {
              name: f.get("name"),
              agent_a: f.get("agent_a"),
              agent_b: f.get("agent_b"),
              allocation_a: Number(f.get("split")) / 100,
            });
            onCreated();
          } catch (err) {
            setError(err.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="Experiment name">
          <input
            name="name"
            required
            defaultValue="Support version comparison"
          />
        </Field>
        {["a", "b"].map((v, i) => (
          <Field key={v} label={`Agent ${v.toUpperCase()}`}>
            <select name={"agent_" + v} defaultValue={agents[i]?.id}>
              {agents.map((a) => (
                <option key={a.id}>{a.id}</option>
              ))}
            </select>
          </Field>
        ))}
        <Field label="Traffic to A (%)">
          <input
            name="split"
            type="number"
            min="1"
            max="99"
            defaultValue="50"
            required
          />
        </Field>
        <p className="muted">
          Assignments use a stable hash of experiment and subject IDs. The same
          subject stays in the same variant.
        </p>
        {error && <p className="error">{error}</p>}
        <div className="modal-actions">
          <button className="primary" disabled={busy || agents.length < 2}>
            {busy ? "Creating…" : "Create experiment"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function ExperimentDetail({ value, onClose }) {
  return (
    <Modal title={value.name} onClose={onClose} wide>
      <p className="muted">{value.note}</p>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Variant</th>
              <th>Agent</th>
              <th>Runs</th>
              <th>Execution success</th>
              <th>Mean latency</th>
              <th>Mean cost</th>
            </tr>
          </thead>
          <tbody>
            {["a", "b"].map((v) => (
              <tr key={v}>
                <td>{v.toUpperCase()}</td>
                <td>{value["agent_" + v]}</td>
                <td>{value.results[v].total_runs}</td>
                <td>{percent(value.results[v].success_rate)}</td>
                <td>{latency(value.results[v].avg_latency_ms)}</td>
                <td>{money(value.results[v].avg_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Output quality</h3>
      <p className="muted">
        Scores cover judged runs only. Unjudged variants have no quality
        estimate.
      </p>
      <div className="table-scroll section-gap">
        <table>
          <thead>
            <tr>
              <th>Variant</th>
              <th>Judged runs</th>
              <th>Correctness</th>
              <th>Relevance</th>
              <th>Safety</th>
              <th>Completeness</th>
              <th>Tool success</th>
            </tr>
          </thead>
          <tbody>
            {["a", "b"].map((v) => (
              <tr key={v}>
                <td>{v.toUpperCase()}</td>
                <td>{value.results[v].judged_runs}</td>
                {["correctness", "relevance", "safety", "completeness"].map(
                  (d) => (
                    <td key={d}>
                      {percent(value.results[v].judge_scores?.[d])}
                    </td>
                  ),
                )}
                <td>{percent(value.results[v].tool_success_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!value.results.a.total_runs && !value.results.b.total_runs && (
        <Empty>
          Choose this experiment in Execute agent and supply a subject ID to
          collect results.
        </Empty>
      )}
    </Modal>
  );
}
