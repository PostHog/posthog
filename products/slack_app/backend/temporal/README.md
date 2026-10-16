# Slack app Temporal workflows

The Slack app workflows and activities run on `settings.TASKS_TASK_QUEUE`.
The worker registers them through `products/slack_app/backend/facade/temporal.py`.
For general Temporal conventions, read [`posthog/temporal/AGENTS.md`](../../../../posthog/temporal/AGENTS.md).

## Local eval scripts

- [`eval_slack_repo_selection.py`](./eval_slack_repo_selection.py) — exercises the Slack `@PostHog` repo-selection cascade (cascade → Haiku gate → discovery agent) against a real team with a connected GitHub integration. Pass/fail summary, no Slack needed. Run as a file (`python products/slack_app/backend/temporal/eval_slack_repo_selection.py --list-cases`), not via `python -m` — the latter would force `backend/temporal/__init__.py` to load activities before `django.setup()`.

## Checking the Slack repo discovery agent

Quick sanity checks that `discover_posthog_code_repository_via_agent_activity` is working after a deploy:

- **Temporal UI.** Filter `slack-app-mention-processing` runs. Healthy: `discover_posthog_code_repository_via_agent_activity` followed by `create_posthog_code_task_for_repo_activity`. Picker-fallback (`post_posthog_code_repo_picker_activity` after the agent) is fine occasionally, alarming if dominant.
- **Slack smoke test.** In a channel with the app and >1 connected repo, `@PostHog Desktop` a message that doesn't name a repo (e.g. "investigate the failing checkout test"). A 🔍 reaction within ~10–60s means the agent ran; the task starting on a real repo means it picked one. A picker on a clear request = something's off.
