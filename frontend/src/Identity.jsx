import { useEffect, useState } from "react";
import App from "./App";
import { api } from "./api";
import { Field, Modal } from "./components";
import WorkspaceSettings from "./WorkspaceSettings";

function Login({ onClose, onSuccess }) {
  const [signup, setSignup] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <Modal
      title={signup ? "Create your account" : "Welcome back"}
      onClose={onClose}
    >
      <p className="muted">
        {signup
          ? "Your agents and traces stay in your private workspace."
          : "Sign in to your workspaces with your email and password."}
      </p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          setBusy(true);
          const f = new FormData(e.target);
          try {
            const data = await api(`auth/${signup ? "signup" : "login"}`, {
              email: f.get("email"),
              password: f.get("password"),
              ...(signup ? { name: f.get("name") } : {}),
            });
            onSuccess(data);
          } catch (err) {
            setError(err.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        {signup && (
          <Field label="Your name">
            <input name="name" autoComplete="name" maxLength={60} required />
          </Field>
        )}
        <Field label="Email address">
          <input
            type="email"
            name="email"
            autoComplete="email"
            maxLength={254}
            required
          />
        </Field>
        <Field
          label="Password"
          hint="Use at least 12 characters. Passwords are stored as salted hashes."
        >
          <input
            type="password"
            name="password"
            autoComplete={signup ? "new-password" : "current-password"}
            minLength={12}
            maxLength={128}
            required
          />
        </Field>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="modal-actions">
          <button
            type="button"
            onClick={() => {
              setSignup(!signup);
              setError("");
            }}
          >
            {signup ? "Already have an account?" : "Create an account"}
          </button>
          <button className="primary" disabled={busy}>
            {busy ? "Please wait…" : signup ? "Create account" : "Sign in"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export default function Identity() {
  const [session, setSession] = useState(null);
  const [workspaceId, setWorkspaceId] = useState("demo");
  const [loginOpen, setLoginOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [invite, setInvite] = useState(() =>
    new URLSearchParams(location.hash.slice(1)).get("invite"),
  );
  const [error, setError] = useState("");
  const [accepting, setAccepting] = useState(false);

  function applySession(value, selected) {
    const saved = selected || localStorage.getItem("agentguard-workspace");
    const id =
      saved === "demo"
        ? "demo"
        : value.workspaces.find((w) => w.id === saved)?.id ||
          value.workspaces[0]?.id ||
          "demo";
    sessionStorage.removeItem("agentguard-token");
    sessionStorage.setItem("agentguard-workspace", id);
    localStorage.setItem("agentguard-workspace", id);
    setWorkspaceId(id);
    setSession(value);
  }
  async function reload(selected) {
    const value = await api("auth/session");
    applySession(value, selected);
  }
  useEffect(() => {
    if (location.hash.startsWith("#invite="))
      history.replaceState(null, "", location.pathname + location.search);
    reload().catch((e) => setError(e.message));
    const expired = () => reload("demo").catch((e) => setError(e.message));
    window.addEventListener("agentguard-session-expired", expired);
    return () =>
      window.removeEventListener("agentguard-session-expired", expired);
  }, []);

  const selected = session?.workspaces.find((w) => w.id === workspaceId);
  const access = {
    ...session,
    workspaceId,
    workspace: selected,
    isDemo: workspaceId === "demo",
    role: selected?.role || "viewer",
  };
  if (!session)
    return (
      <div className="auth-loading">
        <h1>AgentGuard</h1>
        <p>{error || "Opening your workspace…"}</p>
        {error && (
          <button onClick={() => reload().catch((e) => setError(e.message))}>
            Retry
          </button>
        )}
      </div>
    );
  return (
    <>
      <App
        key={`${session.user?.id || "guest"}:${workspaceId}:${selected?.role || "viewer"}`}
        access={access}
        onLogin={() => setLoginOpen(true)}
        onSettings={() => setSettingsOpen(true)}
        onWorkspaceChange={(id) => applySession(session, id)}
        onLogout={async () => {
          try {
            await api("auth/logout", {});
            applySession(
              { user: null, workspaces: [], is_operator: false },
              "demo",
            );
          } catch (e) {
            setError(e.message);
          }
        }}
      />
      {error && (
        <div className="account-error" role="alert">
          {error}
          <button onClick={() => setError("")}>Dismiss</button>
        </div>
      )}
      {loginOpen && (
        <Login
          onClose={() => setLoginOpen(false)}
          onSuccess={(value) => {
            applySession(value, value.workspaces[0]?.id || "demo");
            setLoginOpen(false);
          }}
        />
      )}
      {settingsOpen && (
        <WorkspaceSettings
          access={access}
          onClose={() => setSettingsOpen(false)}
          onChanged={(id) => reload(id).catch((e) => setError(e.message))}
        />
      )}
      {invite && !loginOpen && (
        <Modal title="Workspace invitation" onClose={() => setInvite(null)}>
          <p>
            {session.user
              ? "Accept this invitation to join the team. Your account email must match the invitation."
              : "Sign in or create an account using the email address this invitation was intended for."}
          </p>
          <div className="modal-actions">
            <button
              className="primary"
              disabled={accepting}
              onClick={async () => {
                if (!session.user) {
                  setLoginOpen(true);
                  return;
                }
                setAccepting(true);
                try {
                  const w = await api("auth/invitations/accept", {
                    token: invite,
                  });
                  setInvite(null);
                  await reload(w.id);
                } catch (e) {
                  setError(e.message);
                } finally {
                  setAccepting(false);
                }
              }}
            >
              {accepting
                ? "Joining…"
                : session.user
                  ? "Accept invitation"
                  : "Sign in to accept"}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
