import { Activity, CheckCheck, Timer, Coins } from "lucide-react";
import { money, percent, latency } from "./api";
import { Gate, LatencyChart, TraceTable } from "./components";
export default function Overview({
  overview,
  onRun,
  onSuite,
  onTrace,
  onSeed,
  busy,
}) {
  if (!overview) return <p className="muted">Loading workspace…</p>;
  const s = overview.summary;
  const metrics = [
    [
      "Total runs",
      s.total_runs,
      Activity,
      `${overview.agent_count} registered agent versions`,
    ],
    [
      "Success rate",
      percent(s.success_rate),
      CheckCheck,
      "Execution success · not answer quality",
    ],
    [
      "Avg latency",
      latency(s.avg_latency_ms),
      Timer,
      `p95 ${latency(s.p95_latency_ms)}`,
    ],
    ["Total cost", money(s.total_cost), Coins, "USD · configured token rates"],
  ];
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>Agent performance</h1>
          <p>Quality, cost, and latency across your agents.</p>
        </div>
        <div className="actions">
          <button onClick={onRun}>Execute agent</button>
          <button className="primary" onClick={onSuite}>
            Run evaluation <span>↗</span>
          </button>
        </div>
      </div>
      {!overview.agent_count && (
        <div className="welcome">
          <div>
            <h2>Your first quality checkpoint</h2>
            <p>
              Load two demo agent versions and five gold cases, then run a
              baseline. No API key needed.
            </p>
          </div>
          <button className="primary" disabled={busy} onClick={onSeed}>
            Load demo workspace
          </button>
        </div>
      )}
      {s.demo_runs > 0 && (
        <div className="demo-note">
          <span className="dot" />
          {s.demo_runs} deterministic demo runs included. Demo tokens are
          estimates and cost is $0.
        </div>
      )}
      <div className="metrics">
        {metrics.map(([title, value, Icon, note]) => (
          <section key={title}>
            <div className="metric-label">
              {title}
              <Icon size={17} />
            </div>
            <strong>{value}</strong>
            <small>{note}</small>
          </section>
        ))}
      </div>
      <div className="overview-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>Recent run latency</h2>
            <span className="muted">Milliseconds · latest 12 runs</span>
          </div>
          <LatencyChart runs={overview.recent_runs} />
        </section>
        <section className="panel gate">
          <div className="panel-heading">
            <h2>Deployment gate</h2>
            <span className="mono muted">CI</span>
          </div>
          <Gate suite={overview.recent_suites[0]} />
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>Recent traces</h2>
          <span className="muted">Every step, accounted for</span>
        </div>
        <TraceTable runs={overview.recent_runs} onSelect={onTrace} />
      </section>
    </>
  );
}
