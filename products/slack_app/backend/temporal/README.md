# Slack app Temporal workflows

The Slack app workflows and activities run on `settings.TASKS_TASK_QUEUE`.
The worker registers them through `products/slack_app/backend/facade/temporal.py`.
For general Temporal conventions, read [`posthog/temporal/AGENTS.md`](../../../../posthog/temporal/AGENTS.md).

## Evals

- Repository selection for `@PostHog` mentions (cascade → needs-repo classifier → discovery agent) is evaluated by the harness suite [`slack_app/eval_repo_selection_routing`](../../evals/eval_repo_selection_routing.py) on a synthetic repository catalog, with no real team or Slack traffic. Run it with `hogli evals slack_app/eval_repo_selection_routing`; see the [eval harness guide](../../../posthog_ai/eval_harness/README.md#repository-selection-evals).

## Checking the Slack repo discovery agent

Quick sanity checks that `discover_posthog_code_repository_via_agent_activity` is working after a deploy:

- **Temporal UI.** Filter `slack-app-mention-processing` runs. Healthy: `discover_posthog_code_repository_via_agent_activity` followed by `create_posthog_code_task_for_repo_activity`. Picker-fallback (`post_posthog_code_repo_picker_activity` after the agent) is fine occasionally, alarming if dominant.
- **Slack smoke test.** In a channel with the app and >1 connected repo, `@PostHog Desktop` a message that doesn't name a repo (e.g. "investigate the failing checkout test"). A 🔍 reaction within ~10–60s means the agent ran; the task starting on a real repo means it picked one. A picker on a clear request = something's off.
