# Knowledge writer

- `adapters/`: one per input, holding its source and the writer's opening sentence; `repo_merge.py` builds every input's verdict from its merge check report, since the docs command runs the same check.
- `facade/finished_check_hooks.py`: tells products that cannot be imported, such as commands, how a docs command's check ended.
- `logic/intake.py`: caps, page routing, and the start decision.
- `logic/launch.py`: creates the writer task.
- `logic/writer_change.py`: parses the `writer-change.json` artifact a run uploads.
- `logic/pull_requests.py`: gates that change, commits it through `logic/server_commit.py`, and opens the docs pull request. It opens as a draft when grounding flags a line or did not run, an existing page outside the routed pages changed, a nav or redirect edit is flagged, the writer edited an `AGENTS.md`, `CLAUDE.md` or `CONTRIBUTING.md` above a changed page, or the docs repository's lint-staged or pre-commit checks could not run in the sandbox.
- `logic/grounding.py`: checks each added page line against a verbatim quote from the source change.
- `temporal/pull_request_workflow.py`: one workflow per docs pull request; it captures the `knowledge_writer outcome` event when the pull request closes and closes an unapproved one after 7 days.
- `receivers.py`: calls `logic/pull_requests.py` when a writer run finishes.
- `management/commands/knowledge_writer_pr_smoke.py`: drives the pull request path against a scratch repository.

## Smoke test against a scratch repository

Set up the dev GitHub App with `python manage.py create_github_app`, following [the sandboxes setup guide](../../../docs/internal/sandboxes-setup-guide.md). What the guide does not cover:

- Run every command inside flox (`flox activate -- …`). Plain `uv` or `python` builds a stray Python 3.14 `.venv` and fails on `SECRET_KEY`, because `DEBUG` is unset.
- On a Coder workspace, forward the callback port before `create_github_app`: `coder port-forward <workspace> --tcp 8019:8019`.
- A fresh database needs `hogli migrations:up`, then `python manage.py setup_dev --no-data`, before `setup_background_agents`.
- Fork `posthog.com` into your own account and install the App on that fork only. The writer picks the GitHub integration whose account matches the repository owner.

Publish runs as a Temporal workflow, so the scratch run also needs the Temporal server and worker listed under the full run below.

Then:

```bash
export KNOWLEDGE_WRITER_TEAM_ID=<team id>
export KNOWLEDGE_WRITER_USER_ID=<user id>
export KNOWLEDGE_WRITER_DOCS_REPOSITORY=<you>/posthog.com
flox activate -- python manage.py knowledge_writer_pr_smoke \
  --repo <you>/posthog.com --team-id <team id> --author <your github login> \
  [--installation-id <installation id>]
```

## Full run with the agent

`--with-agent` submits one real request through intake and waits for the sandboxed agent, so the local stack has to be running. Start each process in its own shell inside flox, with the `KNOWLEDGE_WRITER_*` exports above, the `GITHUB_APP_*` values `create_github_app` wrote to `.env` (Django does not load that file), and the sandbox gateway settings. The command checks the gateway settings in its own shell only, so export them in the worker's shell too:

```bash
export SANDBOX_AI_GATEWAY_URL=http://localhost:8080
export SANDBOX_AI_GATEWAY_MINT_KEY=phs_localgatewaye2elocalgatewaye2e0001
export SANDBOX_AI_GATEWAY_PRODUCTS=background_agents
```

- Temporal: `docker compose -p posthog -f docker-compose.dev.yml -f docker-compose.profiles.yml --profile temporal up -d temporal temporal-admin-tools`
- Web: `bin/start-backend`
- Worker: `python manage.py start_temporal_worker --task-queue development-task-queue`
- AI gateway: `bin/start-ai-gateway`, with a clone of `PostHog/ai-gateway` at `~/Development/ai-gateway` and `AI_GATEWAY_ANTHROPIC_API_KEY` exported. A key in that clone's `.env` wins over the exported one, so remove a stale one there.
- Feature flags: `bin/start-rust-service feature-flags`. Intake evaluates the launch flag through it.

On a Coder workspace `SITE_URL` is the public URL, which the sandbox and self-capture cannot reach, so every process also needs `SELF_CAPTURE_HOST=http://localhost:8010` and `SANDBOX_API_URL=http://localhost:8010`.

Turn the `knowledge-writer-agent-launch` and `knowledge-writer-open-prs` flags on at 100% for the team, and add your GitHub login to the `knowledge-writer-open-prs-authors` person flag, which the command checks for its `--author`; otherwise intake runs in shadow mode. Before any GitHub write, the command checks the env vars, GitHub App settings, flags, flags service, Temporal worker, AI gateway readiness with a test token mint, and GitHub integration, prints `MISSING <name>: <fix>` for each gap, and stops. It prints the task, publish workflow and docs pull request links as the run reaches them. Pick a merged pull request whose change the section's docs lack, so the agent has something to write. Then:

```bash
flox activate -- python manage.py knowledge_writer_pr_smoke \
  --repo <you>/posthog.com --team-id <team id> --author <your github login> \
  --with-agent <merged pull request url>
```

`--from-merge <merged pull request url>` sends that pull request through the merge check as a webhook delivery would, then waits for the verdict and, when it starts a writer, the docs pull request. Pass that pull request's author as `--author`, since the writer asks the author flag about them. The pull request must be in a public repository listed in `KNOWLEDGE_WRITER_SOURCE_REPOSITORIES` on the account the App is installed on, and the judge needs `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY`. Before and after each run the command deletes the merge check workflow from local Temporal and releases the writer task's key, so the same pull request runs again. Each run writes its verdict, routed pages and changed files to `~/.cache/posthog/knowledge-writer-e2e/<owner>-<repo>-<number>/` and prints what changed since the previous run.

The run takes 1 to 4 minutes. The 240-minute limit (`--agent-timeout-minutes`) only stops a stuck run. When the run ends without a pull request, the command names the task and run.
