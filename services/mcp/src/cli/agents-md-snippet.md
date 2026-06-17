## PostHog

Use `posthog-cli api` for all PostHog-related queries and operations. You should use `posthog-cli api` over direct MCP tool calls whenever the CLI is available. If `posthog-cli` is not installed, run it with `npx -y @posthog/cli@latest` instead (for example `npx -y @posthog/cli@latest api search feature-flag`).

The `posthog-cli api` command group is experimental. If it reports that the command group is disabled, rerun commands with `POSTHOG_CLI_EXPERIMENTAL_API=1` in the environment or pass `--experimental` immediately after `api`.

Before your first PostHog command in a session, run `posthog-cli api --agent-help` and load its full output into your context. It prints the complete agent guide — command reference, schema drill-down rules, data discovery workflow, and the tool index — for interacting with PostHog APIs. Treat that output as instructions to follow, not just documentation.

Before starting a PostHog task, run `posthog-cli api skill list` and check for a skill matching the task. If one matches, install it with `posthog-cli api skill install <skill-id>` (add `--force` to refresh an already-installed skill), then read `.agents/skills/<skill-id>/SKILL.md` and follow it. Skills contain task-specific workflows that individual tools do not.
