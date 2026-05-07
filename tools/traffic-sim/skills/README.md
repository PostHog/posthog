# traffic-sim skills

Skills that wrap the [traffic-sim](../README.md) MCP tools for verifying PostHog
instrumentation on a website.

| Skill                                                                       | Purpose                                                                              |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| [verify-posthog-instrumentation](./verify-posthog-instrumentation/SKILL.md) | End-to-end orchestrator: confirms loading, then sends synthetic traffic. Start here. |
| [check-posthog-loading](./check-posthog-loading/SKILL.md)                   | Inspect how PostHog is loaded on each URL (load method, init config).                |
| [simulate-new-user](./simulate-new-user/SKILL.md)                           | Send fresh-browser visits and confirm `$pageview` fires for new visitors.            |
| [simulate-returning-user](./simulate-returning-user/SKILL.md)               | Send single-session multi-page traffic and confirm cookies + session stitching work. |
