---
name: generating-ad-hoc-ai-report
description: >
  Generate a one-off LLM-synthesized PostHog report from a free-text prompt and
  return the markdown directly — no schedule, no recipient, no DB row. Use when
  the user asks "what's going on with X?" or wants to render an analytical
  summary themselves. For recurring delivery to email or Slack, use
  `creating-ai-subscription` instead.
---

# Generating an ad-hoc AI report

Use this skill when the user wants a **one-off** report right now. The tool runs the
same planner → HogQL → synthesis pipeline that powers recurring AI subscriptions
and returns rendered markdown — no schedule, no email/Slack delivery, no
persisted subscription row.

## Tools

| Tool                                     | Purpose                                     |
| ---------------------------------------- | ------------------------------------------- |
| `posthog:subscriptions-ai-report-create` | Generate the report and return the markdown |

## What you need before calling

Same three gates as creating a recurring AI subscription. If the call returns 403,
the user must fix one of these before retrying:

1. **PostHog Cloud, or `DEBUG=true`** — self-hosted production is not eligible.
2. **Org-level "AI data processing approved"** — toggle in `Org settings → Data`.
3. **`SUBSCRIPTION_AI_PROMPT` feature flag enabled** for the organization.

## Required arguments

```yaml
prompt: '...' # ≤4000 chars; what to report on
```

## Optional arguments

```yaml
window_days: 7 # how many days back the planner should consider; default 7, max 365
ai_config: # rarely needed; whitelisted models only
  model: 'gpt-4.1-mini'
  planner_model: 'gpt-4.1-mini'
```

## Response

```json
{
  "markdown": "# Weekly product pulse\n\n..."
}
```

The markdown is commonmark with embedded HogQL result tables. Render it directly
to the user — it's already designed to be human-readable.

## Examples

### "What's going on with sign-ups lately?"

```yaml
prompt: 'Summarize new user sign-ups over the last week — top sources, drop-off in onboarding, any new errors.'
window_days: 7
```

### Wider window for a quarterly retro

```yaml
prompt: 'How has weekly active users trended this quarter? Highlight the largest weekly swings and what likely drove them.'
window_days: 90
```

## Pitfalls

- **Cost.** Every call burns LLM tokens (planner + synthesis) plus HogQL execution.
  Throttled by the same rate-limit as scheduled-subscription test deliveries.
  Don't loop this — answer the user's question with one call.
- **`window_days` is a hint, not a hard scope.** The planner is told to consider
  the last N days but is free to pick narrower windows per query step if the data
  warrants it. For deterministic time-bounded queries, write the HogQL yourself
  via `posthog:execute-sql` instead.
- **HogQL errors are swallowed by step.** If one of the planner's query steps
  fails (invalid SQL, ClickHouse timeout), the step is rendered as
  `_Query failed: <ErrorType>_` and the synthesis continues with the remaining
  successful steps. The user gets a partial report, not an error.
- **No persistence.** This tool returns markdown — it does not save a subscription,
  trigger a delivery, or write to the activity log. If the user wants the same
  report tomorrow, suggest `creating-ai-subscription` instead.
- **Don't pass team or user IDs.** They're inferred from the request context. The
  report runs against the project the API token is scoped to, with the calling
  user as the LLM-billed identity.

## When NOT to use this

- The user wants the result emailed or posted to Slack. → `creating-ai-subscription`.
- The user wants a precise SQL query they can run repeatedly. → `posthog:execute-sql`.
- The user wants to explore data interactively across multiple turns. → use the
  list/get tools (`query-trends`, `insights-list`, etc.) directly so each step
  is cheap, bounded, and inspectable.
