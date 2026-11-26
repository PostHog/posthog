# Hogs

Hogs are persistent agents. Each one owns an area of responsibility, works in the background, and messages its owner only when something needs attention. The owner talks to them in a desktop chat app, one contact per hog.

This is a prototype.

## How it fits together

- **Backend** (`backend/`): a hog, its chat messages, schedules, triggers, reports and proposed actions. `logic/runner.py` wakes a hog by starting a task run in the tasks product (profile `hogs.hog`, no repository), or by sending a follow-up to the run that is still alive. `logic/prompt.py` holds the standing instructions every wake starts with.
- **Agent tools** (`mcp/tools.yaml`): the hog reaches the world through PostHog MCP tools. `hog-say` sends the owner a chat message, `hog-report` publishes a finding as a card in the chat, `hog-propose-action` asks before anything outside PostHog, `hog-update` saves its charter and memory, `hog-schedule-create` and `hog-trigger-create` set up future wakes, `hog-tell` sends a note to another hog, and `hog-done` ends a wake.
- **Schedules**: the `fire_due_hog_schedules` Celery beat task runs every minute and wakes hogs whose schedules are due.
- **Triggers** (`logic/triggers.py`): a trigger is an address that wakes a hog when another system posts an event to it. The hog reads the event as untrusted data. An event with an `Idempotency-Key` header, or an `id` in its body, wakes the hog once.
- **Reports** (`logic/reports.py`): a report has a priority from p0 to p4, an impact sentence, a proposal and evidence. It shows as a card in the hog's chat. The owner can have the hog implement or investigate it, or resolve or dismiss it, from the card.
- **Needs you**: a hog with a pending approval, or an open report the owner has not acted on, moves to the top of the chat list and keeps a "Needs you" label. Reading the chat does not clear it. Only acting on the card does.
- **Approval gate** (`logic/approvals.py`): a hog proposes each action outside PostHog. The owner's rule for that kind of action decides: allow, ask or deny. With no rule, the action waits as a card in the chat. Approving wakes the hog to carry it out. The hog has no tool to approve an action or change a rule. The gate depends on the hog proposing first: nothing yet stops a hog from calling an MCP store tool directly.
- **Limits** (`logic/runner.py`): a hog takes at most 60 automatic wakes an hour, and a chain of notes between hogs stops after 4 hops. The owner's own messages always get through.
- **MCP servers**: a hog gets only the MCP store installations assigned to it, through the connector allowlist in the run state.
- **Desktop app** (`desktop/`): a native app for macOS and Windows, written in Rust with GPUI and GPUI Kit. It draws on the GPU with no webview, signs in with PostHog (OAuth with PKCE), and polls the hogs API.

## Run it locally

Start the PostHog dev stack with the `ai_features` and `ai_gateway` capabilities, so the Temporal worker, the MCP server and the AI gateway are up. Then:

```bash
products/hogs/desktop/scripts/run-macos.sh
```

The script builds the app with Cargo, wraps it in `target/Hogs.app` and starts it. It needs rustup, which installs the Rust version pinned in `desktop/rust-toolchain.toml`. On Windows, run `cargo run --release` in `products/hogs/desktop`.

Choose **Local** on the sign-in screen. To skip the browser sign-in during development, start the app with `HOGS_DEV_TOKEN` set to a personal API key that has the `task:write`, `user:read` and `project:read` scopes.

Building the app changes files under `products/hogs/desktop/target`, which makes the Django dev server reload. The first request after a build can take several seconds for that reason.

## Fire a trigger

Ask a hog to create a trigger, or create one with `POST /api/projects/:project_id/hogs/:hog_id/triggers/create/`. Open the hog's details in the app to copy the trigger's address. Then post any JSON to it with an API key that has the `task:write` scope:

```bash
curl -X POST "$POSTHOG_HOST/api/projects/$PROJECT_ID/hogs/$HOG_ID/triggers/$TRIGGER_ID/fire/" \
  -H "Authorization: Bearer $POSTHOG_API_KEY" -H "Content-Type: application/json" \
  -H "Idempotency-Key: deploy-4f9c2ab" -d '{"event": "deploy_finished", "service": "web"}'
```
