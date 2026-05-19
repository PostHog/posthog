# ADR 0002 — LLM-summarised session intents

- **Status:** Accepted (intent-source contract). The session-level summary table referenced as the planned upgrade is being built in parallel and is out of scope of PR [#58407](https://github.com/PostHog/posthog/pull/58407).
- **Owner:** team-posthog-ai.
- **Related code:**
  - [`products/mcp_analytics/backend/intent_clustering.py`](../../backend/intent_clustering.py) — `fetch_intent_corpus`, `embed_intents_async`, constants.
  - [`products/mcp_analytics/backend/models.py`](../../backend/models.py) — `MCPSession.intent`.

## Context

The intent-clustering surface needs a single short text per session that describes _what the user was trying to do_.
"Tool name" alone is not informative — `query_run` covers everything from "show me yesterday's signups" to "find a churn cohort". The cluster view exists precisely because the raw tool stream isn't enough.

Two questions:

1. **Where does the intent text come from?**
2. **How does the cluster pipeline read it?**

We want a contract between the two that lets us upgrade the source without changing the algorithm.

## Decision

**Contract.** `fetch_intent_corpus(team) -> (records, intent_by_session)` is the single integration point between the intent source and the rest of the clustering pipeline. Everything downstream (`embed_intents_async`, `cluster_embeddings`, `build_snapshot`, `aggregate_journeys_per_cluster`) operates on the records it returns.

**Source for v1.** The MCP agent stamps a `$mcp_intent` property on a representative event in the conversation. `fetch_intent_corpus` reads this from ClickHouse `events`, lookback `DEFAULT_LOOKBACK_DAYS = 7`, sample size `DEFAULT_TOP_N_INTENTS = 500`. The same intent text is denormalised onto [`MCPSession.intent`](../../backend/models.py) at session-aggregate time so the session-list surface can show it without a second join.

**Source for v1.x.** A session-level LLM-summarised intent table is being built in parallel. When it lands, `fetch_intent_corpus` is the only function whose body changes — it switches from reading the per-event `$mcp_intent` property to reading from the new table. The pipeline downstream is unaware.

**Embedding model.** `EMBEDDING_MODEL = "text-embedding-3-small-1536"` with prefix `"User intent: "` is the canonical embedding for clustering. We use OpenAI embeddings via [`posthog.api.embedding_worker.async_generate_embedding`](../../../../posthog/api/embedding_worker.py) so cost, rate limiting, and circuit breaking are shared with other PostHog AI features. The constant lives at the top of [`intent_clustering.py`](../../backend/intent_clustering.py) so swapping models is a one-line change.

## Consequences

**Positive**

- Intent source can be upgraded under the contract without touching algorithm, surfaces, or stored snapshots.
- `MCPSession.intent` is populated from the same source the cluster view uses, so users will not see a "session lists this as X, cluster view groups it as Y" inconsistency.
- Embedding model is centralised — one constant, one set of tests, swap is mechanical.

**Negative**

- v1 intent quality depends on the agent's prompt to emit `$mcp_intent`. A noisy agent produces noisy clusters. We expect this; the planned summary upgrade addresses it.
- `DEFAULT_TOP_N_INTENTS = 500` caps the corpus. A team with very long-tail intent vocabulary will under-cluster the tail. Acceptable for v1; we can raise the cap when we know the cost profile.
- We are coupled to OpenAI's embedding endpoint via the shared worker. A provider outage takes the cluster view down. Read-only fallback (showing the most recent successful snapshot) is preserved via [`MCPIntentClusterSnapshot`](../../backend/models.py); see [ADR 0003](./0003-intent-clustering-snapshot.md).

## Alternatives considered

- **Cluster on tool sequences only.** Rejected. The Sankey-style per-cluster journey is informative _given_ a cluster, but tool sequences alone do not separate "investigating churn" from "checking yesterday's signups" when both call `query_run` followed by `insight_get`.
- **Cluster on raw event property bags.** Rejected. Property bags are noisy, high-cardinality, and would need an explicit feature-engineering step. The intent text + embedding pipeline gets us a working v1 without any of that.
- **Skip the `fetch_intent_corpus` indirection and read `$mcp_intent` directly inside the Celery task.** Rejected — the explicit boundary is the entire point. The clustering pipeline is the part we want to be able to test against a hand-crafted corpus without standing up an embedding service or ClickHouse, and the planned source-of-truth swap is much safer with a single seam.
