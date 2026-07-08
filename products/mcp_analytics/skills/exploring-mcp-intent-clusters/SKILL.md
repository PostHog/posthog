---
name: exploring-mcp-intent-clusters
description: >
  Explore PostHog MCP intent clusters — agent goals grouped by semantic
  similarity, with each cluster's tool distribution and error rates. Use when the
  user asks "what are agents trying to do with the MCP?", "group the intents",
  "which goals fail most?", "what does each cluster route to?", wants to
  recompute the clustering, or pastes an MCP analytics intent-clustering URL.
---

# Exploring MCP intent clusters

Intent clustering takes the free-text `$mcp_intent` values agents attach to
their tool calls, embeds them, and groups semantically similar goals into
clusters. Each cluster carries its tool distribution, call counts, and error
rates — answering "what are people _trying_ to do, and does it work?" rather
than "which tool was called".

Unlike tool quality and sessions (which are plain HogQL over `$mcp_tool_call`),
clustering needs embeddings and is **not expressible in SQL**. It is served by
two typed tools backed by a stored snapshot.

## Tools

| Tool                                              | Purpose                                           |
| ------------------------------------------------- | ------------------------------------------------- |
| `posthog:mcp-analytics-intent-clusters-retrieve`  | Fetch the latest cluster snapshot for the project |
| `posthog:mcp-analytics-intent-clusters-recompute` | Trigger an async recompute of the snapshot        |

## Workflow: read the current clusters

```json
posthog:mcp-analytics-intent-clusters-retrieve
{}
```

Returns a snapshot with `status`, `last_computed_at`, `computed_with` (the
embedding model and clustering parameters), and a `clusters` array. Each cluster
has a `label`, `intent_count`, `call_count`, `error_count`, `error_rate_pct`,
`routing_entropy`, a `tool_distribution` (which tools that goal routes to, with
per-tool error rates), and `sample_intents`.

Read clusters by `call_count` for "what are agents mostly doing", or by
`error_rate_pct` for "which goals are failing" — a high error rate on a cluster
points at a class of agent goals the tools serve badly.

`routing_entropy` is how spread-out a cluster's tool usage is: low entropy means
one goal reliably maps to one tool; high entropy means agents are casting around
for the right tool for that goal (often a missing-capability signal).

## Workflow: handle an empty or stale snapshot

- **Empty / idle with no clusters** (`status: idle`, `clusters: []`): no run has
  happened yet. Trigger one (below) and tell the user it computes in the
  background.
- **Stale `last_computed_at`**: offer to recompute.

## Workflow: recompute

```json
posthog:mcp-analytics-intent-clusters-recompute
{}
```

Returns immediately with `status: computing` (HTTP 202); the work runs in the
background. Poll `...-retrieve` until `status` returns to `idle` (done) or
`error`. Don't block waiting — tell the user to re-ask in a minute.

## Constructing UI links

- **Intent clustering**: `https://app.posthog.com/project/<project_id>/mcp-analytics/intent-clustering`

## Tips

- Clusters are only as good as the `$mcp_intent` coverage — if few calls carry
  an intent, clusters will be sparse; cross-check intent coverage with a quick
  `countIf(toString(properties.$mcp_intent) != '')` over `$mcp_tool_call`
- A cluster with high `error_rate_pct` plus high `routing_entropy` is the
  strongest "the tools don't serve this goal well" signal — worth a closer look
  at its `sample_intents` and `tool_distribution`
- Recompute is throttled to one run at a time per project; a 202 while already
  computing just re-confirms the in-flight run

## Related skills

- [`exploring-mcp-tool-quality`](../exploring-mcp-tool-quality/SKILL.md) —
  per-tool error rates and latency
- [`exploring-mcp-sessions`](../exploring-mcp-sessions/SKILL.md) — the individual
  runs behind the intents
