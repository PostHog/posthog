# Cloud runs

Cloud runs are AI agents that execute code tasks in isolated sandboxes. A user creates a task (title, description, repository), clicks "Run task", and the system provisions a sandbox, clones the repo, starts an agent server, and waits for the agent to complete its work and (optionally) create a PR.

## Architecture

```text
                                     PostHog API
                                    ┌─────────────┐
                  POST /run         │ TaskViewSet  │
User ─────────────────────────────►│   .run()     │
                                    │              │
                                    └──────┬───────┘
                                           │ execute_task_processing_workflow()
                                           ▼
                                    ┌─────────────┐
                                    │   Temporal   │
                                    │   Client     │
                                    │              │
                                    └──────┬───────┘
                                           │ start_workflow("process-task")
                                           ▼
                              ┌────────────────────────────┐
                              │  ProcessTaskWorkflow       │
                              │                            │
                              │  1. get_task_processing    │
                              │     _context               │
                              │  2. get_sandbox_for        │
                              │     _repository            │
                              │  3. start_agent_server     │
                              │  4. wait_condition         │
                              │     (5 min inactivity      │
                              │      timeout, heartbeat-   │
                              │      extended)             │
                              │  5. cleanup_sandbox        │
                              └─────────┬──────────────────┘
                                        │
                              ┌─────────▼──────────────────┐
                              │        Sandbox             │
                              │  ┌──────────────────────┐  │
                              │  │  agent-server (npx)  │  │
                              │  │  ┌────────────────┐  │  │
                              │  │  │ @posthog/agent │  │  │
                              │  │  │  (runAgent.mjs)│  │  │
                              │  │  └────────────────┘  │  │
                              │  └──────────────────────┘  │
                              │  /tmp/workspace/repos/…    │
                              └────────────────────────────┘
```

## Components

### PostHog API

`backend/api.py` — `TaskViewSet.run` creates a `TaskRun` (status=QUEUED) and calls `execute_task_processing_workflow()` which starts the Temporal workflow. `TaskRunViewSet.partial_update` handles status transitions and signals the Temporal workflow on terminal statuses via `_signal_workflow_completion`.

### Temporal workflow

`backend/temporal/process_task/workflow.py` — The `process-task` workflow orchestrates the full lifecycle:

1. **get_task_processing_context** — Loads the TaskRun, validates GitHub integration and repository, builds a `TaskProcessingContext` with IDs and credentials
2. **get_sandbox_for_repository** — Creates an OAuth token, provisions a sandbox (with snapshot if available), clones the repo, stores `sandbox_id`/`sandbox_url`/`sandbox_connect_token` in TaskRun.state
3. **start_agent_server** — Runs `npx agent-server` inside the sandbox, waits for health check
4. **wait_condition** — Blocks with a 5-minute inactivity timeout. The agent sends `heartbeat` signals to keep the workflow alive; each heartbeat resets the timer. The workflow exits when it receives a `complete_task` signal or when no heartbeat arrives within 5 minutes
5. **cleanup_sandbox** — Destroys the sandbox container (always runs via `finally`)

### Temporal client

`backend/temporal/client.py` — `execute_task_processing_workflow()` (sync) and `execute_task_processing_workflow_async()` check the `tasks` feature flag, then fire-and-forget the workflow. Workflow IDs follow the pattern `task-processing-{task_id}-{run_id}`.

### Sandbox providers

`backend/services/sandbox.py` — Protocol-based abstraction. `get_sandbox_class()` returns `DockerSandbox` when `SANDBOX_PROVIDER=docker` (requires `DEBUG=True`), otherwise `ModalSandbox`.

- **DockerSandbox** (`backend/services/docker_sandbox.py`) — Local dev. Internal port 47821 (host port is dynamically assigned), no auth token needed. Automatically rewrites `POSTHOG_API_URL` so the container can reach the host: `localhost`/`127.0.0.1` → `host.docker.internal`, port `8010` (Caddy) → `8000` (Django direct, since Caddy returns empty responses from inside Docker). `SANDBOX_API_URL` should not be set when using Docker — the auto-transform handles it. Builds images from `backend/sandbox/images/Dockerfile.sandbox-base`.
- **ModalSandbox** (`backend/services/modal_sandbox.py`) — Production. Port 8080, gVisor isolation, Modal connect tokens for authenticated access. Images from `ghcr.io/posthog/posthog-sandbox-base`.

### Agent server and runner

Inside the sandbox, `npx agent-server` starts an HTTP server on the configured port. The server uses `@posthog/agent` SDK to execute the task. `scripts/runAgent.mjs` is the entrypoint that initializes the `Agent` class and calls `agent.runTaskCloud(taskId, runId, ...)`.

Environment variables consumed inside the sandbox:

| Variable                   | Purpose                                              |
| -------------------------- | ---------------------------------------------------- |
| `GITHUB_TOKEN`             | GitHub installation access token for repo operations |
| `POSTHOG_PERSONAL_API_KEY` | OAuth access token (6h TTL) for PostHog API          |
| `POSTHOG_API_URL`          | PostHog instance URL                                 |
| `POSTHOG_PROJECT_ID`       | Team ID for API scoping                              |
| `JWT_PUBLIC_KEY`           | Public key for verifying sandbox connection tokens   |

## End-to-end flow

1. `POST /api/projects/{team_id}/tasks/{task_id}/run/` — Creates a TaskRun (QUEUED), triggers workflow
2. Temporal starts `process-task` workflow on the `tasks-task-queue` (or `development-task-queue` in DEBUG)
3. **get_task_processing_context** — Loads task, validates state, returns `TaskProcessingContext`
4. **update_task_run_status** — Sets status to IN_PROGRESS
5. **get_sandbox_for_repository** — Gets GitHub token from integration, creates OAuth access token, provisions sandbox, clones repo (unless snapshot used), stores sandbox credentials in TaskRun.state
6. **start_agent_server** — Starts `npx agent-server` in sandbox, polls `/health` until ready
7. **wait_condition** — Workflow blocks with a 5-minute inactivity timeout, extended by `heartbeat` signals from the agent. Twig IDE or the agent server signals completion via the API
8. Agent server calls `PATCH /api/projects/{team_id}/task_runs/{run_id}/` with terminal status
9. API handler sends `complete_task(status, error_message)` signal to the Temporal workflow
10. **cleanup_sandbox** — Sandbox destroyed

## Data model

### Task

Top-level entity representing a unit of work. Fields: `title`, `description`, `repository` (org/repo format), `github_integration`, `origin_product` (user_created, error_tracking, eval_clusters, etc.), `task_number` (auto-incremented per team).

### TaskRun

Execution record for a task. Status lifecycle: `QUEUED -> IN_PROGRESS -> COMPLETED | FAILED | CANCELLED`. The `state` JSON field stores runtime data (`sandbox_id`, `sandbox_url`, `sandbox_connect_token`, `mode`). Logs are stored in S3 as JSONL files.

### SandboxSnapshot

Cached sandbox filesystem images for faster startup. Tracks `external_id` (provider-specific), `repos` (list of cloned repos), `status` (in_progress/complete/error).

### SandboxEnvironment

Per-team configuration for sandbox execution: network access level (trusted/full/custom), allowed domains, encrypted environment variables, repository scope.

## Authentication and security

| Mechanism       | Details                                                                                                           |
| --------------- | ----------------------------------------------------------------------------------------------------------------- |
| Feature flag    | `tasks` — checked in `client.py` before starting workflow                                                         |
| Array OAuth app | Region-specific client IDs (US/EU/DEV) in `backend/temporal/oauth.py`. Creates scoped OAuth tokens with 6h expiry |
| Sandbox JWT     | RS256 tokens from `backend/services/connection_token.py`. 24h expiry, audience `posthog:sandbox_connection`       |
| GitHub App      | Installation access tokens via the team's GitHub integration                                                      |
| API permissions | `PostHogFeatureFlagPermission` + `APIScopePermission` on all endpoints                                            |

## Sandbox providers

|                   | DockerSandbox                                                  | ModalSandbox                                                          |
| ----------------- | -------------------------------------------------------------- | --------------------------------------------------------------------- |
| Use case          | Local development                                              | Production                                                            |
| Internal port     | 47821                                                          | 8080                                                                  |
| Host port         | Dynamically assigned                                           | N/A (cloud-routed)                                                    |
| Isolation         | Standard Docker container                                      | gVisor kernel-level sandboxing                                        |
| Auth              | No token needed                                                | Modal connect token                                                   |
| Image source      | Local Dockerfile build                                         | `ghcr.io/posthog/posthog-sandbox-base`                                |
| Snapshots         | Docker commit/tag                                              | Modal `snapshot_filesystem()`                                         |
| URL rewriting     | Auto (`localhost` → `host.docker.internal`, `:8010` → `:8000`) | None (uses `SANDBOX_API_URL` or ngrok)                                |
| `SANDBOX_API_URL` | Not needed (auto-transform handles it)                         | Only for local dev with Modal (ngrok URL); production uses `SITE_URL` |

### Local development with Docker

Docker is the recommended sandbox provider for local development. To use it, set `SANDBOX_PROVIDER=docker` and `DEBUG=1` in your `.env`.

**Do not set `SANDBOX_API_URL`** when using Docker. The `DockerSandbox` automatically rewrites `POSTHOG_API_URL` inside the container:

- `localhost` / `127.0.0.1` → `host.docker.internal` (Docker's host gateway)
- Port `8010` (Caddy) → `8000` (Django directly) — Caddy returns empty responses when called from inside Docker

The container is started with `--add-host host.docker.internal:host-gateway` so `host.docker.internal` resolves to the host machine. The internal agent-server port is 47821; the host port is dynamically assigned to avoid conflicts.

Setting `SANDBOX_API_URL` is unnecessary with Docker — the auto-transform already does the right thing. If you need to override, use port 8000: `SANDBOX_API_URL=http://host.docker.internal:8000`.

### Local development with Modal

To use Modal sandboxes locally, set these environment variables:

```bash
MODAL_TOKEN_ID=your_token_id
MODAL_TOKEN_SECRET=your_token_secret
SANDBOX_API_URL=https://your-subdomain.ngrok.dev
```

Get tokens from [modal.com](https://modal.com).

`SANDBOX_API_URL` is the URL the Modal sandbox uses to call back to your local PostHog instance. Since Modal runs in the cloud, it can't reach `localhost`. Use a tunnel like ngrok to expose your local Django server:

```bash
ngrok http 8000
```

Set `SANDBOX_API_URL` to the ngrok URL. `SITE_URL` stays as `http://localhost:8010` so that the rest of the stack (feature flags, self-capture, etc.) continues to work against localhost.

### Images

- `Dockerfile.sandbox-base` — Base image with Node.js, `@posthog/agent` from npm, git
- `Dockerfile.sandbox-notebook` — Extends base with Jupyter/notebook support
- `Dockerfile.sandbox-local` — Dev overlay that replaces npm `@posthog/agent` with local packages

## Frontend

- **TaskDetailPage** (`frontend/components/TaskDetailPage.tsx`) — Task detail view with run history, "Run task" button, "Open in Twig" link
- **TaskSessionView** (`frontend/components/TaskSessionView.tsx`) — Live log streaming with hedgehog animation during agent execution
- Twig IDE integration via `twig://task/{id}` deep links

## Key files

| File                                        | Role                                                          |
| ------------------------------------------- | ------------------------------------------------------------- |
| `backend/api.py`                            | REST API — TaskViewSet, TaskRunViewSet                        |
| `backend/models.py`                         | Task, TaskRun, SandboxSnapshot, SandboxEnvironment            |
| `backend/temporal/client.py`                | Workflow triggering, feature flag check                       |
| `backend/temporal/process_task/workflow.py` | ProcessTaskWorkflow orchestration                             |
| `backend/temporal/process_task/activities/` | Workflow activities (context, sandbox, agent server, cleanup) |
| `backend/services/sandbox.py`               | Sandbox protocol and provider selection                       |
| `backend/services/docker_sandbox.py`        | DockerSandbox implementation                                  |
| `backend/services/modal_sandbox.py`         | ModalSandbox implementation                                   |
| `backend/services/connection_token.py`      | JWT token generation                                          |
| `backend/temporal/oauth.py`                 | Array OAuth app, token creation                               |
| `backend/sandbox/images/`                   | Dockerfiles for sandbox images                                |
| `scripts/runAgent.mjs`                      | Agent runner entrypoint in sandbox                            |
| `scripts/run_agent_in_docker.py`            | Local test script                                             |
| `frontend/components/TaskDetailPage.tsx`    | Task detail UI                                                |
| `frontend/components/TaskSessionView.tsx`   | Live log streaming UI                                         |
| `posthog/settings/temporal.py`              | Temporal and sandbox settings                                 |
