# Knowledge writer

- `adapters/`: turn a source event (the docs command, …) into a docs request.
- `logic/intake.py`: caps, section routing, and the start-or-join decision.
- `logic/launch.py`: creates the writer task.
- `logic/pull_requests.py`: opens a draft docs pull request, or comments a joined request's source on the open one.
- `receivers.py`: calls `logic/pull_requests.py` when a writer run finishes.
- `management/commands/knowledge_writer_pr_smoke.py`: drives the pull request path against a scratch repository.

## Smoke test against a scratch repository

Set up the dev GitHub App with `python manage.py create_github_app`, following [the sandboxes setup guide](../../../docs/internal/sandboxes-setup-guide.md). What the guide does not cover:

- Run every command inside flox (`flox activate -- …`). Plain `uv` or `python` builds a stray Python 3.14 `.venv` and fails on `SECRET_KEY`, because `DEBUG` is unset.
- On a Coder workspace, forward the callback port before `create_github_app`: `coder port-forward <workspace> --tcp 8019:8019`.
- A fresh database needs `hogli migrations:up`, then `python manage.py setup_dev --no-data`, before `setup_background_agents`.
- Fork `posthog.com` into your own account and install the App on that fork only. The writer picks the GitHub integration whose account matches the repository owner.

Then:

```bash
export KNOWLEDGE_WRITER_TEAM_ID=<team id>
export KNOWLEDGE_WRITER_USER_ID=<user id>
export KNOWLEDGE_WRITER_DOCS_REPOSITORY=<you>/posthog.com
flox activate -- python manage.py knowledge_writer_pr_smoke \
  --repo <you>/posthog.com --team-id <team id> [--installation-id <installation id>]
```

## Full run with the agent

`--with-agent` submits two real requests through intake and waits for the sandboxed agent, so the local stack has to be running. Start each process in its own shell inside flox, with the `KNOWLEDGE_WRITER_*` exports above:

- Temporal: `docker compose -p posthog -f docker-compose.dev.yml -f docker-compose.profiles.yml --profile temporal up -d temporal temporal-admin-tools`
- Web: `bin/start-backend`
- Worker: `python manage.py start_temporal_worker --task-queue development-task-queue`
- LLM gateway: `bin/start-llm-gateway` with the `llm-gateway` env from `bin/mprocs.yaml` and `LLM_GATEWAY_ANTHROPIC_API_KEY`. Without `LLM_GATEWAY_DEBUG=true` the gateway rejects the local OAuth app with a 403.
- Feature flags: `bin/start-rust-service feature-flags`. Intake evaluates the launch flag through it.

On a Coder workspace `SITE_URL` is the public URL, which the sandbox and self-capture cannot reach, so every process also needs `SELF_CAPTURE_HOST=http://localhost:8010`, `SANDBOX_API_URL=http://localhost:8010` and `SANDBOX_LLM_GATEWAY_URL=http://host.docker.internal:3308`.

Turn the `knowledge-writer-agent-launch` flag on at 100% for the team; otherwise intake runs in shadow mode and the command stops. Pick two merged pull requests whose change the section's docs lack, so the agent has something to write. Then:

```bash
flox activate -- python manage.py knowledge_writer_pr_smoke \
  --repo <you>/posthog.com --team-id <team id> \
  --with-agent <merged pull request url> <merged pull request url>
```

Each run takes about 2 minutes. The 240-minute limit on both (`--agent-timeout-minutes`) only stops a stuck run. When the first run ends without a pull request, the command names the task and run and leaves any branch the agent pushed.
