# Cloud runs: local setup guide

Step-by-step instructions to get cloud runs running locally.

## 1. GitHub App setup

Create a GitHub App with these permissions:

| Permission    | Access       | Purpose                                   |
| ------------- | ------------ | ----------------------------------------- |
| Contents      | Read & Write | Read files, create branches, push commits |
| Pull requests | Read & Write | Create and update PRs                     |
| Metadata      | Read         | Required for all GitHub Apps              |

Optional: Issues (R/W), Workflows (R/W).

Steps:

1. GitHub -> Settings -> Developer Settings -> GitHub Apps -> New GitHub App
2. Set the **Setup URL** to `http://localhost:8010/integrations/github/callback`
3. Set the permissions above
4. Generate and download a private key
5. Install the app on your test repositories

Add to your `.env`:

```bash
GITHUB_APP_CLIENT_ID=your_app_id
GITHUB_APP_SLUG=your-app-slug
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
```

The app slug is the URL-friendly name in your GitHub App URL (e.g., `github.com/apps/your-app-slug`). The private key can include literal `\n` characters — they'll be converted to newlines.

## 2. Array OAuth app setup

Cloud runs create scoped OAuth tokens to give the agent access to the PostHog API. This requires an `OAuthApplication` record in the database.

For **local development**, this is created automatically when you run `generate_demo_data`.

The client ID `DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ` is the dev constant from `backend/temporal/oauth.py`. Tests create this automatically via the `autouse=True` fixture in `conftest.py`.

## 3. Environment variables

Add to your `.env`:

```bash
# Required: DEBUG must be enabled for DockerSandbox
DEBUG=1

# Sandbox provider (required for local dev)
SANDBOX_PROVIDER=docker

# SANDBOX_API_URL is not needed when using Docker.
# DockerSandbox auto-rewrites POSTHOG_API_URL inside the container:
#   localhost/127.0.0.1 → host.docker.internal
#   port 8010 (Caddy) → 8000 (Django direct, Caddy returns empty responses from Docker)
# If you must override, use port 8000: SANDBOX_API_URL=http://host.docker.internal:8000

# JWT keys for OAuth and sandbox connections - get these from .env.example
SANDBOX_JWT_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
OIDC_RSA_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"

# GitHub App (from step 1)
GITHUB_APP_CLIENT_ID=your_app_id
GITHUB_APP_SLUG=your-app-slug
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

# Optional: for local agent development (see step 7)
# LOCAL_TWIG_MONOREPO_ROOT=/path/to/twig
```

## 4. Feature flag

Create a `tasks` feature flag at 100% rollout:

1. Navigate to Feature flags in PostHog
2. Create a new flag with key `tasks`
3. Set rollout to 100%
4. Save

This is the feature flag used on the endpoints and in the temporal worker.

## 5. Temporal worker

Temporal and the temporal-django-worker start automatically via mprocs when you run `./bin/start`.

The `process-task` workflow defined in `products/tasks/backend/temporal/process_task/workflow.py` provisions a sandbox, starts an agent inside it, and waits for the agent to finish. The workflow orchestrates these activities:

1. **get_task_processing_context** — Loads the TaskRun from the database, validates the GitHub integration and repository, and builds a `TaskProcessingContext` carrying all the IDs needed by later activities
2. **get_sandbox_for_repository** — Creates an OAuth access token, provisions a Docker sandbox (reusing a snapshot if one exists), clones the repository, and stores the sandbox URL in `TaskRun.state`
3. **start_agent_server** — Runs `npx agent-server` inside the sandbox and polls `/health` until it responds
4. **wait_condition** — The workflow blocks with a 5-minute inactivity timeout, extended by `heartbeat` signals from the agent. Exits on a `complete_task` signal or when no heartbeat arrives within 5 minutes
5. **cleanup_sandbox** — Destroys the sandbox container (always runs, even on failure)

The activities live in `products/tasks/backend/temporal/process_task/activities/`.

## 6. Running via the UI

This is very minimal at the moment, but the tasks page can be used to see what is happening with a background cloud run.

1. Navigate to Tasks in PostHog (requires the `tasks` feature flag)
2. Create a task with a title, description, and repository (format: `owner/repo`)
3. Click "Run task"
4. Watch logs stream in the session view

## 7. Testing with local agent packages

To test changes to `@posthog/agent` before publishing:

```bash
# Set the twig monorepo root
export LOCAL_TWIG_MONOREPO_ROOT=/path/to/twig

# Build the packages first
cd /path/to/twig/packages/agent && pnpm build

# Run a task from the UI
```

This builds a `posthog-sandbox-base-local` Docker image that overlays your local `packages/agent`, `packages/shared`, and `packages/git` onto the base image. The local image is rebuilt each time; the base image is cached. If you make changes to the base image, you can rebuild it.

## Troubleshooting

| Problem                            | Solution                                                                                                                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Docker not running                 | Start Docker Desktop or the Docker daemon                                                                                                                                                  |
| Temporal not reachable             | Ensure Temporal is running on `127.0.0.1:7233`. Check with `temporal server start-dev`                                                                                                     |
| Feature flag not enabled           | Create the `tasks` flag at 100% rollout (see step 4)                                                                                                                                       |
| Array OAuth app missing            | Run the Django shell command in step 2                                                                                                                                                     |
| GitHub token expired               | Tokens from GitHub App installations expire after ~1 hour. Re-run the task to get a fresh token                                                                                            |
| "Task workflow execution blocked"  | The `tasks` feature flag is not enabled for this user/org                                                                                                                                  |
| Sandbox image build fails          | Check Docker has enough disk space. Delete old images with `docker system prune`                                                                                                           |
| Agent server health check fails    | Check sandbox logs: `docker exec <container_id> cat /tmp/agent-server.log`                                                                                                                 |
| `SANDBOX_JWT_PRIVATE_KEY` missing  | Generate an RSA key (see step 3) and add it to your `.env`                                                                                                                                 |
| Port conflict on sandbox host port | DockerSandbox maps container port 47821 to a dynamic host port. Check sandbox logs or TaskRun state for the assigned port; if another process uses it, stop that process or restart Docker |
| Sandbox can't reach PostHog API    | Don't set `SANDBOX_API_URL` with Docker — auto-transform handles it. If overriding, use port 8000, not 8010 (Caddy returns empty responses from inside Docker)                             |
| `DEBUG` not set                    | `SANDBOX_PROVIDER=docker` requires `DEBUG=1`. Without it, you'll get "DockerSandbox cannot be used in production"                                                                          |
