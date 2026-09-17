# Server deployment

AgentGuard is packaged as one Docker service: the React assets are built in a Node stage, and FastAPI serves the dashboard and API from the final Python image. Runtime dependencies are installed from `uv.lock`. Local databases, credentials, virtual environments, and QA artifacts are excluded from the deployment archive and Docker build context.

## Railway

AgentGuard is deployed in the Railway account selected by the user (`s.karthikeyan5401@gmail.com`).

- Public URL: **https://agentguard-production-2392.up.railway.app**
- Project: `ff718b1d-12b2-40d6-a473-ff163986d552`
- Service: `b56101b7-4b37-4b37-9c81-63d2357cf3a5` (`agentguard`)
- Environment: `0f95a6d4-3886-4b4f-97ef-a1ad58ec8fe1` (`production`)
- Persistent volume: `fa9c2e3a-5020-418b-bc88-abbf0d8121d3`
- Management: https://railway.com/project/ff718b1d-12b2-40d6-a473-ff163986d552

The workspace token is stored in Railway's service variables and the ignored local `.env.production` file. Create an account, then connect the original workspace under **Workspace & account - Your account** using `AGENTGUARD_API_TOKEN` from that file. This is an application access token, not an OpenAI API key.

Deployment settings:

| Setting | Value |
| --- | --- |
| Build | Repository-root `Dockerfile` |
| Service | `agentguard` |
| Replicas | **1**, because this implementation uses SQLite |
| Persistent volume | Mount at `/data` **before the first deployment** |
| Database | `AGENTGUARD_DB=/data/agentguard.db` (image default) |
| Bind | `AGENTGUARD_HOST=0.0.0.0` (image default) |
| Port | `PORT=8000`, domain target port 8000 |
| Authorization | A newly generated, high-entropy `AGENTGUARD_API_TOKEN` stored as a service secret |
| Health check | `/api/health`, configured in `railway.toml` |

The container prepares the volume mount directory as root, then drops to UID 10001 before running the application. It fails to start on the public bind address without a workspace token. Set `AGENTGUARD_PUBLIC_URL` to the public HTTPS origin. Visitors use the public demo or sign up; only the installation owner needs the original token to claim the original workspace. Do not put it in a URL or commit it to source control.

The local workspace is linked to this Railway service. Deploy code updates with `railway up --service agentguard --detach`. A GitHub repository is not required. Keep the existing volume and token across deployments. Do not recreate the project or volume when shipping updates.

## Existing VPS

Use a Linux server with Docker, a persistent data volume, and an HTTPS reverse proxy. Build from this directory:

```sh
docker build -t agentguard:latest .
docker volume create agentguard-data
```

Supply the generated workspace token through a server-side secret/env file with owner-only permissions, then run:

```sh
docker run -d --name agentguard --restart unless-stopped \
  --env-file /secure/path/agentguard.env \
  -p 127.0.0.1:8000:8000 \
  -v agentguard-data:/data \
  agentguard:latest
```

Point the server's HTTPS reverse proxy to port 8000. Keep the container port bound to loopback when using that proxy. Provider keys and OTel export configuration remain server-side environment settings.

## Required verification after deployment

1. Public `/api/health` returns `status: ok` and `auth_required: true`.
2. Public dashboard and its built assets load over HTTPS.
3. `/api/agents` without a token and with an incorrect token returns HTTP 401.
4. A correctly authenticated request can register and execute the deterministic demo agent.
5. Redeploy/restart the service and verify the recorded run still exists on the persistent volume.

Railway successfully built and started the Docker image. The hosted smoke test verified HTTPS assets, required authentication, rejection of missing/incorrect tokens, a successful agent run, and a five-case demo suite with 100% exact-match/schema accuracy. Verification data is saved locally in ignored `data/hosted-verification.json`.

The service was then redeployed successfully as `2e549799-94c6-45aa-bd8a-f7c957cda167`; the original run and evaluation suite remained accessible, confirming persistent-volume storage across deployments. Hosted desktop/mobile login, dashboard metrics, and trace inspection also passed the browser check on 2026-09-15.

Run `uv run python deploy/verify_hosted.py https://agentguard-production-2392.up.railway.app --check-persistence` after a redeployment to verify that the original run and suite remain available. Run `node verify-hosted.mjs` inside `frontend/` to check the hosted browser flow. Neither script prints the workspace token.

Live OpenAI, Anthropic, Gemini, and hosted OpenTelemetry/Langfuse integrations still require their provider credentials. The deployment is operational with the deterministic demo provider.

## Multi-workspace rollout

Deployment `0c0cf5ed-1613-4977-ad36-8f4d884544c8` succeeded. Hosted checks passed for anonymous desktop/mobile demo browsing, trace inspection, sign-up, Secure/HttpOnly cookies, login/logout, private agent execution, workspace isolation, cross-origin rejection, and read-only demo enforcement. The original run and suite remained accessible after migration. Two synthetic deployment-verification accounts remain, with live AI disabled. Local verification covered 60 backend tests (59 full-suite checks followed by 15 account checks including the added migration-backup test), two browser flows, lint, and the production build.

Before adding account tables to an existing database, startup creates a consistent SQLite backup named `agentguard.db.before-accounts.bak` alongside the original database. It does not overwrite this backup on subsequent starts.

Set `AGENTGUARD_PUBLIC_URL=https://agentguard-production-2392.up.railway.app` for secure cookies and same-origin mutation checks. Account tables migrate additively in the original database; private workspace files live under `/data/workspaces`, and public fixtures live in `/data/public-demo.db`. Preserve the whole volume. Sessions, invitation hashes, membership, and daily reservations persist across restarts.

The public demo allows GET requests only. Private API reads require a session and workspace membership, or the original bearer token for the legacy workspace only. Live provider access is disabled for new workspaces until the operator approves it and configures `AGENTGUARD_MODEL_PRICES` plus provider credentials. Authentication currently supports email/password with manually shared invitation links, without email verification/recovery or Google OAuth.
