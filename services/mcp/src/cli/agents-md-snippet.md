## PostHog

Use `posthog-cli api` for all PostHog-related data queries and operations. You should use `posthog-cli api` over direct MCP tool calls whenever the CLI is available.

Before your first PostHog command in a session, run `posthog-cli api --agent-help` and load its full output into your context. It prints the complete agent guide — command reference, schema drill-down rules, data discovery workflow, and the tool index — for interacting with PostHog APIs. Treat that output as instructions to follow, not just documentation.

Before starting a PostHog task, run `posthog-cli api skill list` and check for a skill matching the task. If one matches, install it with `posthog-cli api skill install <skill-id>` (add `--force` to refresh an already-installed skill), then read `.agents/skills/<skill-id>/SKILL.md` and follow it. Skills contain task-specific workflows that individual tools do not.
