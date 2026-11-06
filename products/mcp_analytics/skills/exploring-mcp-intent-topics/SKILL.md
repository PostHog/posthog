---
name: exploring-mcp-intent-topics
description: >
  Explore PostHog MCP intent topics — every agent intent embedded and assigned to a
  stable topic, with per-tool focus, trend, drift, outliers, similar tools and a 2D
  map. Use when the user asks "what do agents use my MCP server for?", "how is tool X
  used?", "has the use of tool X changed over the past 3 months?", "what is the average
  use of tool X over the past 5 days?", "is the intent for tool X consolidated or all
  over the place?", "what are the outlier uses of tool X?", "which tools have a similar
  intended use as tool X?", or wants to read the intents inside a topic.
---

# Exploring MCP intent topics

Every `$mcp_tool_call` that carries a `$mcp_intent` is embedded and assigned to one
intent topic. Topics keep their ids across weekly re-fits, so a share can be compared
across months. All four tools below read a nightly rollup, so they answer in seconds
for any window. Only `toolName` and `dateRange` filter; shared property filters do not
apply. Every answer carries `coverage`: how many calls carried an intent and how many
of those have a topic. Quote it when it is below about 80%.

Attribution is per call and per text: a call counts only when it carries its own
intent. Calls without an intent are not in any topic.

## Question to tool

| Question                                                   | Tool                                                                                  |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| "What do agents use this server for?"                      | `posthog:query-mcp-intent-topics` without `toolName`                                  |
| "How is tool X used?" / "what for?"                        | `posthog:query-mcp-tool-intent-profile` — read `results` (top topics) and `focus`     |
| "What is the average use of tool X over the past 5 days?"  | `posthog:query-mcp-tool-daily-stats` with an explicit 5-day `dateRange`: average the  |
|                                                            | daily calls. Topic sparklines cover only the top topics and skip calls without one    |
| "How has use of tool X changed over the past 3 months?"    | `posthog:query-mcp-intent-topics` with `toolName` and `dateRange` = last 90 days;     |
|                                                            | `trend_pp` compares with the 90 days before. For a finer story, call it per month     |
| "Where is tool X drifting?"                                | `posthog:query-mcp-tool-intent-profile` — `drift.new`, `growing`, `shrinking`, `gone` |
| "Is tool X consolidated or all over the place?"            | `posthog:query-mcp-tool-intent-profile` — `focus.band` and `focus.score`              |
| "What are the outlier uses of tool X?"                     | `posthog:query-mcp-tool-intent-profile` — `outliers`                                  |
| "Which tools have a similar intended use as tool X?"       | `posthog:query-mcp-similar-tools`                                                     |
| "Show me the intents inside topic T" / "what sits far out" | `posthog:query-mcp-intent-map` with `topicId`, or read `is_outlier` points            |
| "What did the agent say on one call?"                      | `posthog:query-mcp-tool-sample-intents` (raw recent intents, not topics)              |

## Reading the numbers

- `share_pct` is the share of intent-carrying calls in the window. `trend_pp` is the
  change in share versus the previous window of the same length, in percentage points.
  A topic can grow in calls and shrink in share on a growing server; say which one you mean.
- `focus.score` is 1 minus the normalised entropy of calls across topics. Bands:
  consolidated at 0.7 and above, mixed from 0.4, spread below. One topic scores 1.
- Drift lists need at least 5 calls in the period that makes the claim and a 1.5 times
  change in share. Small tools rarely drift by this rule; say so instead of forcing a story.
- Outliers are intents further from their nearest topic than that topic's 95th percentile
  member. `calls` on an outlier is the call count when it was embedded.
- Similar tools compare topic share vectors. Two tools with the same mix score 1 even when
  one is called far more; `calls` tells the volume.
- Map positions are a PCA projection, good for density and neighbourhood, not for distance
  arithmetic. Points carry only the most called intents up to the limit; `total_points`
  says how many matched.

## Workflow

1. Confirm the effective tool name with `posthog:query-mcp-tool-stats` if the user gave a
   loose name.
2. Start with `posthog:query-mcp-intent-topics` or the tool profile for the window the user
   named. Default to the last 7 days.
3. For a change over time, run the same query for the two periods you compare, or read
   `trend_pp`. Name both windows in the answer.
4. Quote topic labels as they are. They are generated and must not contain names or ids;
   if one does, report it as a labelling bug.
5. Link the tool detail page or the intent map when a UI exists for it.

## Related skills

- [`exploring-mcp-tool-usage`](../exploring-mcp-tool-usage/SKILL.md) — volume, errors, latency and who uses a tool.
- [`exploring-mcp-sessions`](../exploring-mcp-sessions/SKILL.md) — what one agent session did, step by step.
