### Sharing feedback on PostHog

The `agent-feedback` tool is a direct channel to the PostHog team for feedback about **anything PostHog** — a product or feature you (or the user) hit a rough edge with, this MCP server itself, the docs, or a capability that's missing.

**Human-in-the-loop is required — always confirm with the user before submitting.** When you or the user run into something worth telling the PostHog team, surface the summary you would send, get the user's explicit go-ahead, and only then call the tool. Never submit feedback silently, autonomously, or without the user having seen and approved it. This is a user-driven side channel, not a background signal.

Set `feedback_type` to route it:

- `product` — any PostHog product or feature: insights, session replay, feature flags, the data warehouse, web analytics, error tracking, experiments, etc. Put the area in `product_area` (e.g. "session replay").
- `mcp` — this MCP server itself: an unclear tool description, a confusing input schema, a hard-to-consume response, wrong results, an unhelpful error, a missing tool, or these instructions. Set `category` for MCP feedback.
- `docs` — PostHog documentation.
- `other` — anything that doesn't fit the above.

**All sentiments are welcome** — set `sentiment` to `positive`, `neutral`, `negative`, or `mixed`. Unlike a bug tracker, praise and feature requests are useful signal too, not just problems. Good triggers: a confusing or broken product experience, a papercut that slowed the task down, a missing capability you had to work around, a feature request, an unhelpful error, or something that worked really well and is worth reinforcing.

Keep it short and actionable: a one-sentence `summary`, then the detail fields (`friction_points`, `suggested_improvement`, `details`) as clear, concise bullet points, quoting the exact product surface, tool name, parameter, or error text where you can. Include a concrete `suggested_improvement` whenever you can name one — for negative or mixed feedback that's the most valuable part. Use `task_completed: false` when you couldn't finish the user's request. Do not include user PII or sensitive query content in any field.

The user can also ask you to send feedback directly — e.g. "make a PostHog feedback for this, it's broken." Even then, capture their point faithfully and show them the summary you'll submit before calling the tool.

Submitting feedback is **not** a way to end your turn or skip work. It's a side report to the PostHog team — call it when warranted, then keep going and finish the user's task with the other tools.
