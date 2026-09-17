import { useEffect, useState } from "react";
import { api, money } from "./api";
import { Empty, Field, Modal } from "./components";

export default function WorkspaceSettings({ access, onClose, onChanged }) {
  const [data, setData] = useState(null);
  const [tab, setTab] = useState(access.isDemo ? "account" : "team");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [inviteLink, setInviteLink] = useState("");
  const [operatorRows, setOperatorRows] = useState([]);
  const owner = data?.workspace.role === "owner";
  async function refresh() {
    if (!access.isDemo)
      setData(await api(`auth/workspaces/${access.workspaceId}`));
    if (access.is_operator)
      setOperatorRows(await api("auth/operator/workspaces"));
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [access.workspaceId]);
  async function act(fn, success = "Saved") {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
      await refresh();
      setMessage(success);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Workspace & account" onClose={onClose} wide>
      <div className="settings-tabs">
        {[
          ...(!access.isDemo ? ["team", "usage"] : []),
          "account",
          ...(access.is_operator ? ["operator"] : []),
        ].map((t) => (
          <button
            key={t}
            className={tab === t ? "primary" : ""}
            onClick={() => {
              setTab(t);
              setError("");
              setMessage("");
            }}
          >
            {t === "team"
              ? "Team & invitations"
              : t === "usage"
                ? "Usage & limits"
                : t === "operator"
                  ? "Operator controls"
                  : "Your account"}
          </button>
        ))}
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="success-note" role="status">
          {message}
        </p>
      )}
      {tab === "team" && data && (
        <>
          <h3>{data.workspace.name}</h3>
          <p className="muted">
            Owners manage the team and limits. Editors create and execute.
            Viewers can inspect and export.
          </p>
          <div className="table-scroll section-gap">
            <table>
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.members.map((m) => (
                  <tr key={m.id}>
                    <td>
                      {m.name}
                      {m.id === access.user.id ? " (you)" : ""}
                    </td>
                    <td>{m.email}</td>
                    <td>
                      {owner ? (
                        <select
                          aria-label={`Role for ${m.email}`}
                          disabled={busy}
                          value={m.role}
                          onChange={(e) =>
                            act(async () => {
                              await api(
                                `auth/workspaces/${access.workspaceId}/members/${m.id}`,
                                { role: e.target.value },
                                "PATCH",
                              );
                              await onChanged(access.workspaceId);
                            })
                          }
                        >
                          {["owner", "editor", "viewer"].map((r) => (
                            <option key={r}>{r}</option>
                          ))}
                        </select>
                      ) : (
                        m.role
                      )}
                    </td>
                    <td>
                      {owner && m.id !== access.user.id && (
                        <button
                          disabled={busy}
                          onClick={() =>
                            act(
                              () =>
                                api(
                                  `auth/workspaces/${access.workspaceId}/members/${m.id}`,
                                  undefined,
                                  "DELETE",
                                ),
                              "Member removed",
                            )
                          }
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {owner && (
            <>
              <h3>Invite a teammate</h3>
              <form
                className="invite-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  const f = new FormData(e.target);
                  act(async () => {
                    const result = await api(
                      `auth/workspaces/${access.workspaceId}/invitations`,
                      { email: f.get("email"), role: f.get("role") },
                    );
                    setInviteLink(`${location.origin}/#invite=${result.token}`);
                  }, "Invitation created. Share the private link with this recipient.");
                }}
              >
                <Field label="Teammate email">
                  <input type="email" name="email" required />
                </Field>
                <Field label="Invitation role">
                  <select name="role">
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                  </select>
                </Field>
                <button className="primary" disabled={busy}>
                  Create invitation
                </button>
              </form>
              {inviteLink && (
                <Field
                  label="Private invitation link"
                  hint="Single use, valid for 7 days. Share it only with the intended recipient. No email is sent automatically."
                >
                  <input
                    value={inviteLink}
                    readOnly
                    onFocus={(e) => e.target.select()}
                  />
                  <button
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(inviteLink);
                        setMessage("Invitation link copied");
                      } catch {
                        setMessage("Select and copy the link above");
                      }
                    }}
                  >
                    Copy invitation link
                  </button>
                </Field>
              )}
              <h3>Pending invitations</h3>
              {data.invitations.length ? (
                data.invitations.map((i) => (
                  <div className="list-row" key={i.id}>
                    <div>
                      {i.email}
                      <small>
                        {i.role} · expires{" "}
                        {new Date(i.expires * 1000).toLocaleDateString()}
                      </small>
                    </div>
                    <button
                      disabled={busy}
                      onClick={() =>
                        act(
                          () =>
                            api(
                              `auth/workspaces/${access.workspaceId}/invitations/${i.id}`,
                              undefined,
                              "DELETE",
                            ),
                          "Invitation revoked",
                        )
                      }
                    >
                      Revoke
                    </button>
                  </div>
                ))
              ) : (
                <Empty>No pending invitations.</Empty>
              )}
            </>
          )}
        </>
      )}
      {tab === "usage" && data && (
        <>
          <h3>Today's usage · {data.usage.day} UTC</h3>
          <div className="usage-grid">
            {[
              ["Agent runs", data.usage.runs, data.workspace.daily_runs],
              ["Model calls", data.usage.calls, data.workspace.daily_calls],
              [
                "Reserved AI budget",
                money(data.usage.reserved_cost),
                money(data.workspace.daily_budget),
              ],
            ].map(([label, used, limit]) => (
              <section key={label}>
                <small>{label}</small>
                <strong>
                  {used} <span>/ {limit}</span>
                </strong>
              </section>
            ))}
          </div>
          <p className="muted">
            Limits are shared by the team and reset at midnight UTC. Costs
            reserve a conservative amount before each live model call;
            reservations remain charged if a call fails. This is budget
            protection, not an invoice.
          </p>
          <p className="access-note">
            Live AI:{" "}
            <strong>
              {data.workspace.live_enabled
                ? "Enabled for approved models"
                : "Disabled · operator approval required"}
            </strong>
          </p>
          {owner && (
            <form
              key={JSON.stringify(data.workspace)}
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.target);
                act(() =>
                  api(
                    `auth/workspaces/${access.workspaceId}/limits`,
                    {
                      daily_runs: Number(f.get("runs")),
                      daily_calls: Number(f.get("calls")),
                      daily_budget: Number(f.get("budget")),
                    },
                    "PATCH",
                  ),
                );
              }}
            >
              <h3>Lower workspace limits</h3>
              <p className="muted">
                Owners may lower limits. Ask the operator for increases.
              </p>
              <div className="form-columns">
                <Field label="Daily runs">
                  <input
                    name="runs"
                    type="number"
                    min="0"
                    max={data.workspace.daily_runs}
                    defaultValue={data.workspace.daily_runs}
                    required
                  />
                </Field>
                <Field label="Daily model calls">
                  <input
                    name="calls"
                    type="number"
                    min="0"
                    max={data.workspace.daily_calls}
                    defaultValue={data.workspace.daily_calls}
                    required
                  />
                </Field>
                <Field label="Daily AI budget (USD)">
                  <input
                    name="budget"
                    type="number"
                    min="0"
                    step="0.01"
                    max={data.workspace.daily_budget}
                    defaultValue={data.workspace.daily_budget}
                    required
                  />
                </Field>
              </div>
              <button className="primary" disabled={busy}>
                Save limits
              </button>
            </form>
          )}
        </>
      )}
      {tab === "account" && (
        <>
          <h3>{access.user.name}</h3>
          <p className="muted">{access.user.email}</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const name = new FormData(e.target).get("name");
              act(async () => {
                const w = await api("auth/workspaces", { name });
                await onChanged(w.id);
                onClose();
              }, "Workspace created");
            }}
          >
            <Field label="New workspace name">
              <input
                name="name"
                maxLength={80}
                required
                placeholder="Research team"
              />
            </Field>
            <button disabled={busy}>Create private workspace</button>
          </form>
          <details>
            <summary>Connect your original token-based workspace</summary>
            <p className="muted">
              Existing data remains private. Only the holder of its original API
              token can claim it. Claiming it also grants operator controls.
            </p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const token = new FormData(e.target).get("token");
                act(async () => {
                  const w = await api("auth/claim-original", { token });
                  await onChanged(w.id);
                  onClose();
                }, "Original workspace connected");
              }}
            >
              <Field label="Original workspace API token">
                <input
                  name="token"
                  type="password"
                  autoComplete="off"
                  required
                />
              </Field>
              <button disabled={busy}>Connect original workspace</button>
            </form>
          </details>
          <details>
            <summary>Change password</summary>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                const form = e.target;
                const f = new FormData(form);
                act(async () => {
                  await api("auth/password", {
                    current_password: f.get("current"),
                    new_password: f.get("next"),
                  });
                  form.reset();
                }, "Password changed. Other sessions have been signed out.");
              }}
            >
              <Field label="Current password">
                <input
                  type="password"
                  name="current"
                  autoComplete="current-password"
                  minLength={12}
                  required
                />
              </Field>
              <Field label="New password">
                <input
                  type="password"
                  name="next"
                  autoComplete="new-password"
                  minLength={12}
                  maxLength={128}
                  required
                />
              </Field>
              <button disabled={busy}>Change password</button>
            </form>
          </details>
        </>
      )}
      {tab === "operator" && (
        <>
          <p className="muted">
            Approve live access and limits per workspace. Live model rates must
            also exist in the server's AGENTGUARD_MODEL_PRICES catalog.
          </p>
          {operatorRows.map((w) => (
            <form
              className="operator-row"
              key={w.id + JSON.stringify(w.usage)}
              onSubmit={(e) => {
                e.preventDefault();
                const f = new FormData(e.target);
                act(() =>
                  api(
                    `auth/operator/workspaces/${w.id}`,
                    {
                      daily_runs: Number(f.get("runs")),
                      daily_calls: Number(f.get("calls")),
                      daily_budget: Number(f.get("budget")),
                      live_enabled: f.get("live") === "on",
                    },
                    "PATCH",
                  ),
                );
              }}
            >
              <h3>{w.name}</h3>
              <small className="mono">{w.id}</small>
              <div className="form-columns">
                <Field label="Daily runs">
                  <input
                    name="runs"
                    type="number"
                    min="0"
                    max="10000"
                    defaultValue={w.daily_runs}
                    required
                  />
                </Field>
                <Field label="Daily calls">
                  <input
                    name="calls"
                    type="number"
                    min="0"
                    max="100000"
                    defaultValue={w.daily_calls}
                    required
                  />
                </Field>
                <Field label="Daily budget (USD)">
                  <input
                    name="budget"
                    type="number"
                    min="0"
                    max="1000"
                    step="0.01"
                    defaultValue={w.daily_budget}
                    required
                  />
                </Field>
              </div>
              <label className="checkbox-label">
                <input
                  name="live"
                  type="checkbox"
                  defaultChecked={!!w.live_enabled}
                />{" "}
                Enable live AI for this workspace
              </label>
              <button disabled={busy}>Save workspace access</button>
            </form>
          ))}
        </>
      )}
    </Modal>
  );
}
