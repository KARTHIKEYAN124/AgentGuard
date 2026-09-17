import { Children, cloneElement, useEffect, useId, useRef } from "react";
import { X, ArrowUpRight, CircleCheck, CircleAlert } from "lucide-react";
import { date, latency, money } from "./api";

export function Status({ value }) {
  const good = ["success", "passed", "completed", "ok"].includes(value);
  return (
    <span
      className={`status ${good ? "good" : value === "running" ? "neutral" : "bad"}`}
    >
      {good ? <CircleCheck size={13} /> : <CircleAlert size={13} />} {value}
    </span>
  );
}
export function Empty({ children }) {
  return <div className="empty">{children}</div>;
}
export function Json({ value }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}
export function Field({ label, children, hint }) {
  const id = useId();
  return (
    <label className="field">
      <span id={`${id}-label`}>{label}</span>
      {Children.map(children, child => ["input", "select", "textarea"].includes(child?.type) ? cloneElement(child, {
        "aria-labelledby": `${id}-label`,
        "aria-describedby": hint ? `${id}-hint` : undefined,
      }) : child)}
      {hint && <small id={`${id}-hint`}>{hint}</small>}
    </label>
  );
}
export function Modal({ title, children, onClose, wide = false }) {
  const ref = useRef(null);
  useEffect(() => {
    const d = ref.current;
    d.showModal();
    return () => d.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? "wide" : ""}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <header>
        <h2>{title}</h2>
        <button className="icon" onClick={onClose} aria-label="Close dialog">
          <X size={19} />
        </button>
      </header>
      {children}
    </dialog>
  );
}
export function TraceTable({ runs, onSelect }) {
  if (!runs.length)
    return (
      <Empty>No traces yet. Execute an agent to capture its first run.</Empty>
    );
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Run / time</th>
            <th>Agent</th>
            <th>Model</th>
            <th>Status</th>
            <th className="number">Latency</th>
            <th className="number">Cost · USD</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td>
                <button
                  className="text-button mono"
                  onClick={() => onSelect(r)}
                >
                  {r.id.slice(0, 8)}
                </button>
                <small>{date(r.created_at)}</small>
              </td>
              <td>{r.agent_id}</td>
              <td>
                <span className="mono">{r.model || "—"}</span>
                {r.provider === "demo" && <small>Deterministic demo</small>}
              </td>
              <td>
                <Status value={r.status} />
              </td>
              <td className="number mono">{latency(r.latency_ms)}</td>
              <td className="number mono">{money(r.cost)}</td>
              <td>
                <button
                  className="icon"
                  aria-label={`Inspect run ${r.id.slice(0, 8)}`}
                  onClick={() => onSelect(r)}
                >
                  <ArrowUpRight size={16} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function Gate({ suite }) {
  if (!suite)
    return (
      <Empty>
        Run a baseline, then compare a candidate to inspect deployment gates.
      </Empty>
    );
  const gate = suite.gate;
  return (
    <>
      <div className="gate-verdict">
        <Status
          value={
            suite.passed
              ? "passed"
              : suite.status === "running"
                ? "running"
                : "blocked"
          }
        />
        <small>{suite.agent_id}</small>
      </div>
      {gate ? (
        gate.checks.map((c) => (
          <div className="gate-row" key={c.metric}>
            <div>
              <span>
                {
                  {
                    accuracy: "Accuracy drop",
                    cost: "Cost increase",
                    latency_ms: "Latency increase",
                  }[c.metric]
                }
              </span>
              <small>
                Limit {(c.limit * 100).toFixed(0)}
                {c.metric === "accuracy" ? " pp" : "%"}
              </small>
            </div>
            <strong className={c.passed ? "green" : "red"}>
              {c.change == null
                ? "Unknown"
                : `${(c.change * 100).toFixed(1)}${c.metric === "accuracy" ? " pp" : "%"}`}
            </strong>
          </div>
        ))
      ) : (
        <p className="muted">
          Baseline run · all gold cases must pass. Select this suite as a
          baseline when evaluating the next version.
        </p>
      )}
    </>
  );
}
export function LatencyChart({ runs }) {
  const points = [...runs].reverse().filter((r) => r.latency_ms != null);
  if (!points.length)
    return <Empty>Latency will appear here after your first run.</Empty>;
  const max = Math.max(...points.map((r) => r.latency_ms), 1) * 1.2;
  const path = points
    .map(
      (r, i) =>
        `${i ? "L" : "M"} ${10 + (i * 620) / Math.max(points.length - 1, 1)} ${155 - (r.latency_ms / max) * 130}`,
    )
    .join(" ");
  return (
    <div className="chart">
      <div className="chart-plot">
        <div className="chart-y" aria-hidden="true">
          {[1, 0.5, 0].map((n) => (
            <span key={n}>{(max * n).toFixed(0)}</span>
          ))}
        </div>
        <svg
          viewBox="0 0 640 175"
          preserveAspectRatio="none"
          role="img"
          aria-label={`Recent latency chart. Maximum ${max.toFixed(1)} milliseconds.`}
        >
          {[0, 0.5, 1].map((n) => (
            <line
              key={n}
              x1="0"
              x2="640"
              y1={155 - n * 130}
              y2={155 - n * 130}
              stroke="#e8edea"
            />
          ))}
          <path
            d={path}
            fill="none"
            stroke="#27825e"
            strokeWidth="2.5"
            vectorEffect="non-scaling-stroke"
          />
          {points.map((r, i) => (
            <circle
              key={r.id}
              cx={10 + (i * 620) / Math.max(points.length - 1, 1)}
              cy={155 - (r.latency_ms / max) * 130}
              r="3.5"
              fill="#27825e"
            >
              <title>
                {r.id.slice(0, 8)} · {latency(r.latency_ms)}
              </title>
            </circle>
          ))}
        </svg>
      </div>
      <div className="chart-x">
        <span>Oldest</span>
        <span>Latest</span>
      </div>
    </div>
  );
}
