# PRD 0001 — MCP analytics v1

- **Status:** Draft, tracks PR [#58407](https://github.com/PostHog/posthog/pull/58407).
- **Owner:** team-posthog-ai.
- **Code root:** [`products/mcp_analytics/`](../../).

## Problem

AI agents (Claude Desktop, Cursor, Cline, Windsurf, in-product PostHog agents) now talk to PostHog through MCP tools.
We have raw `mcp_tool_call` events flowing through capture, but no product surface to answer the questions a team building or hosting MCP tools actually has:

- Which tools are being called? Which are failing or slow?
- What are users actually trying to do — at the level of "find a churn cohort", not "ran `query_run` 14 times"?
- Where do conversations get stuck, give up, or fall through to feedback?

The data is there; the synthesis is not.

## Goal

Ship a focused product surface — **MCP analytics** — that turns raw MCP tool-call events into the four views an MCP operator needs day to day, without forcing them to write HogQL.

## Non-goals

- Replacing LLM analytics. Generation-level traces, prompt/response inspection, and cost belong in `products/llm_analytics/`. MCP analytics is about the *tool-call protocol layer* on top of that.
- Building a generic agent observability framework. We optimise for PostHog's own MCP surface and external MCP servers built on `posthog-js`-style instrumentation.
- Replacing product analytics insights. Where a query is "$pageview by country", users should keep using Trends.

## Surfaces (v1)

Mounted by [`products/mcp_analytics/manifest.tsx`](../../manifest.tsx) under `/mcp-analytics/*`:

| Route | Purpose |
| --- | --- |
| `/mcp-analytics/dashboard` | Overview of MCP activity — sessions, tool calls, error rate, top tools, top clients. Built from dashboard templates in [`backend/dashboard_templates.py`](../../backend/dashboard_templates.py). |
| `/mcp-analytics/sessions` | List of conversations (one row per `$mcp_conversation_id`) with duration, tools used, who the user was, and the inferred intent. |
| `/mcp-analytics/tool-quality` | Per-tool quality view — call count, error rate, p50/p95 duration, top callers — across all tools. |
| `/mcp-analytics/tool-quality/:toolName` | Drill-down for a single tool, including recent calls and recent failures. |
| `/mcp-analytics/intent-clustering` | Aggregated view of *what users are trying to do*: clusters of similar intents with sample sessions and a per-cluster journey Sankey. |

## Surfaces (explicitly out of scope for v1)

- Per-user usage charts beyond what session-list filtering gives you.
- A "compare two MCP servers" view.
- Alerting on MCP tool errors. (Use Error tracking or product alerts.)

## User stories

1. **As an MCP server operator,** I want to see at a glance whether my MCP tools are healthy this week (volume up/down, error rate, p95 latency), so I can decide whether to dig deeper. — Dashboard.
2. **As a product engineer,** I want to inspect a single conversation — what the user was trying to do, what tools the agent called, where it failed — so I can debug a complaint or learn from a long session. — Sessions list → recording link → linked LLM trace.
3. **As a product engineer,** I want a per-tool view to see which of my MCP tools are failing or slow, and who is hitting the failures. — Tool quality.
4. **As a PM/research engineer,** I want to see *what users are using MCP for* (categories of intent, not raw tool counts), so I can prioritise new tools and improve docs for the requests we keep missing. — Intent clustering.
5. **As a user of an MCP tool,** I want to file feedback or a missing-capability report from inside the agent, with enough context attached that the team can act on it. — Feedback submission API ([`MCPAnalyticsSubmission`](../../backend/models.py)).

## Data model

Three Postgres tables, all team-scoped:

- **`MCPSession`** — one row per `$mcp_conversation_id` (the agent-level conversation ID, not the front-end `$session_id`). Aggregated from ClickHouse `events` by a Temporal activity. See [ADR 0001](../adrs/0001-mirror-mcp-sessions-clickhouse-to-postgres.md).
- **`MCPAnalyticsSubmission`** — user-submitted feedback or missing-capability reports, with the MCP context (client name/version, transport, conversation id, trace id) attached at write time.
- **`MCPIntentClusterSnapshot`** — denormalised JSON snapshot of the latest cluster run for a team. See [ADR 0003](../adrs/0003-intent-clustering-snapshot.md).

Raw `mcp_tool_call` events remain in ClickHouse and are the source of truth.
Postgres tables are derived; they can be re-derived from events by re-running the backfill.

## Success criteria

- An MCP operator can answer "is my MCP healthy this week?" from the dashboard in under 30 seconds with no manual querying.
- "What is this session about?" is answerable for ≥90% of sessions ≥3 tool calls, surfaced as an inferred intent on the session row.
- Intent clusters land within 60 seconds of "Recompute" being pressed on a team with up to 500 intents in the last 7 days.
- Feedback submissions persist with full MCP context (client name/version, conversation id, trace id) so they can be filtered and triaged downstream.
- All four surfaces work on a freshly seeded project via `python manage.py seed_mcp_sessions`, with no manual ClickHouse fixture needed.

## Risks

- **Cardinality of intents.** Embedding 500 intents per team per recompute is fine; running this for every team every hour is not. Recompute is user-triggered for v1; we will add scheduled refresh when we have a sense of usage.
- **Embedding cost drift.** `text-embedding-3-small-1536` is cheap today; if OpenAI pricing or rate-limits change we should be able to swap to a self-hosted alternative without rewriting the pipeline. The model name is a constant in [`intent_clustering.py`](../../backend/intent_clustering.py).
- **Conversation-id semantics.** We key sessions on `$mcp_conversation_id`, distinct from the front-end `$session_id`. If MCP clients stop populating it, the entire sessions surface degrades. See [ADR 0001](../adrs/0001-mirror-mcp-sessions-clickhouse-to-postgres.md) for fallbacks.
- **Intent quality.** Today intent text comes from the per-event `$mcp_intent` property emitted by the agent. Quality depends on the agent prompt. The session-level summary table referenced in [ADR 0002](../adrs/0002-llm-summarized-session-intents.md) is the planned upgrade.

## Future work (not v1)

- Scheduled cluster refresh (Celery beat) once we know how many active teams the snapshot is worth maintaining for.
- Switch `fetch_intent_corpus` to read from the session-level summary table once it lands. See [ADR 0002](../adrs/0002-llm-summarized-session-intents.md).
- Cohort/segment breakdowns on the dashboard (e.g. "show me sessions from team plan = paid").
- Cross-MCP-server comparison view.
