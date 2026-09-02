---
name: exploring-mcp-intent-clusters
description: >
  Explore PostHog MCP intent clusters — agent goals grouped by semantic
  similarity, with each cluster's tool distribution and error rates, plus the
  tool-centric pivot (capture rate per intent, discovery rate against the
  advertised catalog, description fit, tool overlaps). Use when the user asks
  "what are agents trying to do with the MCP?", "group the intents", "which
  goals fail most?", "what does each cluster route to?", "when agents have this
  intent do they find my tool?", "which tools get mixed up?", wants to recompute
  the clustering, or pastes an MCP analytics intent-clustering URL.
---

# Exploring MCP intent clusters

Intent clustering takes the free-text `$mcp_intent` values agents attach to
their tool calls, embeds them, and groups semantically similar goals into
clusters. Attribution is per call: each call is credited to its own intent
(calls without one inherit the most recent prior intent in the same session),
so a tool's counts reflect the intent it actually served. Each cluster carries
its tool distribution, call counts, and error rates — answering "what are
people _trying_ to do, and does it work?" rather than "which tool was called".
The snapshot also carries a tool-centric pivot answering the reverse question:
for a given tool, which intents drive its usage, how often do agents find it,
and who does it compete with.

Unlike tool quality and sessions (which ultimately aggregate `$mcp_tool_call`),
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
embedding model, clustering parameters, and sample-coverage percentages), a
`clusters` array, a `tools` array (the tool pivot), and `tool_overlaps`. Each
cluster has a `label`, `intent_count`, `call_count`, `error_count`,
`error_rate_pct`, `routing_entropy`, a `tool_distribution` (which tools that
goal routes to, with per-tool error rates), `sample_intents`, plus `switches`
(errored call immediately followed by a different tool for the same intent —
the strongest "agents mix these tools up" evidence) and `self_retries`
(errored call immediately retried with the same tool — a sign the tool's
error messages aren't helping agents self-correct).

Read clusters by `call_count` for "what are agents mostly doing", or by
`error_rate_pct` for "which goals are failing" — a high error rate on a cluster
points at a class of agent goals the tools serve badly.

`routing_entropy` is how spread-out a cluster's tool usage is: low entropy means
one goal reliably maps to one tool; high entropy means agents are casting around
for the right tool for that goal (often a missing-capability signal).

## Workflow: answer "is my tool discoverable?" from the tool pivot

Each entry in `tools` carries:

- `clusters` — the intent clusters the tool serves, each with `capture_pct`
  (its share of the cluster's calls), `rank`, `top_competitor` (the strongest
  other tool and its share), and `description_fit` (cosine similarity between
  the tool's description and the cluster centroid; null until descriptions are
  captured). Entries carry only `cluster_id`, not the cluster's own label or
  totals — join them against the top-level `clusters` array on that id
- `n_clusters_served` — how many clusters the tool serves in total. The entry
  list above is capped, so compare the two before saying "this tool serves N
  intents"
- `discovery_rate_pct` — of the sampled sessions whose `$mcp_tools_list`
  catalog advertised the tool, the share that actually called it; null when the
  tool was advertised in fewer than 5 sampled sessions
- `contested_score` — call-weighted mean entropy of its clusters: how often its
  intents are split with other tools

High `description_fit` with low `capture_pct` is the discoverability failure:
agents should find the tool for that intent but pick something else. Low fit
with high capture means the description undersells what the tool actually does.
`tool_overlaps` lists pairs competing for the same intents; use
`sessions_with_both` vs `sessions_with_either` to separate workflows (used
together) from confusion (one or the other).

Read coverage before quoting numbers: `computed_with.sampled_sessions` /
`session_coverage_pct` say how much of the window the corpus represents, and
`advertisement_coverage_pct` bounds what discovery rates can see. Only sessions
with an observed tools-list catalog enter discovery denominators, and sessions
in exec-wrapper mode advertise only the wrapper, so per-tool discovery is
measured on full-catalog sessions.

`computed_with` is not a completeness check for everything, though. Only the
top-level tool and overlap-pair caps report what they dropped, via
`dropped_tools` and `dropped_overlap_pairs`. The per-cluster lists are capped
silently, so treat a cluster showing 10 switches or 5 self-retries as "at least
that many", not "exactly". A tool's cluster entries are capped too, but there
`n_clusters_served` gives you the real count.

Clustering reads events only. The on-demand session summaries
(`MCPSession.intent`, what "generate intent" writes) are deliberately left out:
a summary describes a whole session, and spreading it across that session's
calls is the mis-attribution the per-call corpus exists to remove. So a session
whose intent was only ever summarised is not in any cluster — check
`intent_coverage_pct` for how much of the window that leaves out, and read
session summaries directly when you need them.

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
background. Poll `posthog:mcp-analytics-intent-clusters-retrieve` until `status`
returns to `idle` (done) or `error`. Don't block waiting — tell the user to
re-ask in a minute.

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
