---
name: signals
description: 'How to query the document_embeddings table for signals data using HogQL. Read when you need to perform semantic search over signals, fetch signals for a report or list signal types.'
---

# Querying Signals

## What Are Signals?

Signals are automated observations that PostHog generates by monitoring a customer's product data across multiple sources — error tracking, web analytics, experiments, session replay, and more. Each signal is a short natural-language description of something noteworthy (e.g. "Error rate spiked 3× on /checkout").

Signals are grouped into **Signal Reports**. When a report accumulates enough weight it gets summarized and assessed for actionability. A signal report represents a cluster of related observations that together describe a meaningful issue or trend.

Signals and their embeddings are stored in the `document_embeddings` ClickHouse table, queryable via HogQL through the `posthog:execute-sql` MCP tool. They may provide a useful way to semantically query for recent things that happened in the user's product.

## Table and Column Reference

The HogQL table alias is `document_embeddings`. HogQL automatically constrains queries to the current team — you never need to filter on `team_id`. Key columns for signals:

| Column          | Type           | Description                                                                  |
| --------------- | -------------- | ---------------------------------------------------------------------------- |
| `product`       | String         | Product bucket — always `'signals'` for signals                              |
| `document_type` | String         | Document type — always `'signal'` for signals                                |
| `model_name`    | String         | Embedding model — always `'text-embedding-3-small-1536'`                     |
| `document_id`   | String         | Unique signal ID (UUID)                                                      |
| `timestamp`     | DateTime64(3)  | When the signal was created                                                  |
| `inserted_at`   | DateTime64(3)  | When this row version was inserted (used for deduplication and soft deletes) |
| `content`       | String         | The signal description text                                                  |
| `metadata`      | String         | JSON string with report_id, source info, weight, deleted flag, etc           |
| `embedding`     | Array(Float64) | 1536-dimensional embedding vector                                            |

## Mandatory Filters

Every signals query MUST include all four of these filters. Missing any of them can cause the query to fail with an invalid model error, return wrong data, or trigger unnecessarily expensive scans:

```sql
WHERE model_name = 'text-embedding-3-small-1536'
  AND product = 'signals'
  AND document_type = 'signal'
  AND timestamp >= now() - INTERVAL 30 DAY
```

The `model_name` filter is especially critical — the HogQL engine uses it to route to the correct underlying ClickHouse table. If the `WHERE model_name = ...` equality filter is missing or uses an unknown model, the query will fail with an "Invalid model name" error (you cannot use `IN` or other expressions here).

The `product` and `document_type` filters are equally important — the same model contains data from multiple products (e.g. error tracking, AI memory). Without these filters you will get unrelated data mixed in.

The `timestamp` filter is required for performance — the table is partitioned by week and has a 3-month TTL. Always include a time bound using `now() - INTERVAL N DAY` (or `WEEK`, `MONTH`, etc.). Default to 30 days unless you have a reason to look further back. Generally, more recent data is more likely to be relevant, unless investigating a long-standing issue.

## Deduplication Pattern

The underlying table can contain multiple versions of the same signal (e.g. after a soft-delete re-emission). You MUST always deduplicate by wrapping reads in a subquery using `argMax(..., inserted_at)` grouped by `document_id`.

**Note:** HogQL supports `metadata.field_name` dot access on the raw `metadata` JSON column, but this type information is lost when the column passes through aggregate functions like `argMax()`. You MUST extract individual metadata fields inside the inner dedup subquery — do NOT pass the whole `metadata` blob through `argMax` and dot into it in the outer query, as this will fail with a type error.

HogQL's JSON dot access always extracts values as `Nullable(String)`, regardless of the underlying JSON type. This means `metadata.deleted` is the string `'true'`/`'false'`/`null`, not a Bool. Use `deleted != 'true'` — do NOT use `NOT deleted`.

```sql
SELECT ... FROM (
    SELECT
        document_id,
        argMax(content, inserted_at) as content,
        argMax(metadata.report_id, inserted_at) as report_id,
        argMax(metadata.source_product, inserted_at) as source_product,
        argMax(metadata.source_type, inserted_at) as source_type,
        argMax(metadata.deleted, inserted_at) as deleted,
        argMax(embedding, inserted_at) as embedding,
        argMax(timestamp, inserted_at) as signal_ts
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
      AND product = 'signals'
      AND document_type = 'signal'
      AND timestamp >= now() - INTERVAL 1 MONTH
    GROUP BY document_id
)
WHERE deleted != 'true'
```

Only select the `embedding` column in the inner subquery when you actually need it for similarity searches — it's a 1536-element float array and expensive to materialize otherwise.

## The `embedText()` Function

`embedText()` is a HogQL function that converts a text string into an embedding vector at query compile time. It calls the embedding API and inlines the resulting vector as a constant before executing the query. This means you can do semantic search in a single query without any external embedding step.

**Signature:** `embedText(text, model_name)`

- `text` — the string to embed. **Must be a string literal**, not a column reference.
- `model_name` — the embedding model to use. **For signals, always use `'text-embedding-3-small-1536'`.**

Both arguments must be literal strings. You cannot pass column values or expressions — the function resolves at compile time, not per row.

## `cosineDistance()` for Similarity Search

Use `cosineDistance(embedding, ...)` to rank signals by semantic similarity. Lower values = more similar. Always `ORDER BY distance ASC` and add a `LIMIT`.

```sql
cosineDistance(embedding, embedText('your search text', 'text-embedding-3-small-1536')) as distance
```

The embedding model (`text-embedding-3-small-1536`) uses matryoshka representation learning, so the embedding dimensions are ordered by importance. This means similarity search works well even at high dimensionality — the curse of dimensionality is not a significant concern here.

## Metadata JSON Fields

The `metadata` column is a JSON string. HogQL supports `metadata.field_name` dot access **only on the raw table column**. After aggregation (e.g. `argMax`), the JSON type is lost and dot access will fail. Always extract the fields you need inside the dedup subquery.

| Field            | Inner-query access        | Description                                                         |
| ---------------- | ------------------------- | ------------------------------------------------------------------- |
| `report_id`      | `metadata.report_id`      | UUID of the parent Signal Report (empty if unassigned)              |
| `source_product` | `metadata.source_product` | Originating product (use Example 3 to discover available values)    |
| `source_type`    | `metadata.source_type`    | Signal type (use Example 3 to discover available values)            |
| `source_id`      | `metadata.source_id`      | ID of the source entity                                             |
| `weight`         | `metadata.weight`         | Signal weight (contributes to report promotion threshold)           |
| `deleted`        | `metadata.deleted`        | Soft-deletion flag (extracted as String — compare with `!= 'true'`) |
| `extra`          | `metadata.extra`          | Arbitrary JSON blob from the source product                         |
| `match_metadata` | `metadata.match_metadata` | LLM match reasoning stored during grouping                          |

---

## Example 1: Semantic Search for Signals

Find signals most similar to a natural-language query. This is the most useful query for understanding what's happening in a customer's product:

```sql
SELECT
    document_id,
    content,
    report_id,
    source_product,
    source_type,
    cosineDistance(embedding, embedText('users seeing errors on checkout page', 'text-embedding-3-small-1536')) as distance
FROM (
    SELECT
        document_id,
        argMax(content, inserted_at) as content,
        argMax(metadata.report_id, inserted_at) as report_id,
        argMax(metadata.source_product, inserted_at) as source_product,
        argMax(metadata.source_type, inserted_at) as source_type,
        argMax(metadata.deleted, inserted_at) as deleted,
        argMax(embedding, inserted_at) as embedding,
        argMax(timestamp, inserted_at) as signal_ts
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
      AND product = 'signals'
      AND document_type = 'signal'
      AND timestamp >= now() - INTERVAL 1 MONTH
    GROUP BY document_id
)
WHERE deleted != 'true'
ORDER BY distance ASC
LIMIT 10
```

Adjust the `embedText` first argument to whatever you're looking for. Write it as a natural-language description of the kind of issue or observation you want to find.

To restrict to signals that have already been grouped into a report, add `AND report_id != ''` to the outer WHERE.

## Example 2: Fetch All Signals for a Specific Report

Once you have a `report_id` (from a semantic search or from the Signal Reports API), fetch all signals belonging to that report:

```sql
SELECT
    document_id,
    content,
    report_id,
    source_product,
    source_type,
    signal_ts
FROM (
    SELECT
        document_id,
        argMax(content, inserted_at) as content,
        argMax(metadata.report_id, inserted_at) as report_id,
        argMax(metadata.source_product, inserted_at) as source_product,
        argMax(metadata.source_type, inserted_at) as source_type,
        argMax(metadata.deleted, inserted_at) as deleted,
        argMax(timestamp, inserted_at) as signal_ts
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
      AND product = 'signals'
      AND document_type = 'signal'
      AND timestamp >= now() - INTERVAL 3 MONTH
    GROUP BY document_id
)
WHERE report_id = '<report-uuid-here>'
  AND deleted != 'true'
ORDER BY signal_ts ASC
LIMIT 100
```

## Example 3: List Signal Types

See what kinds of signals exist for this customer — returns one example per unique `(source_product, source_type)` pair from the last month:

```sql
SELECT
    source_product,
    source_type,
    count() as cnt,
    max(signal_ts) as latest_timestamp
FROM (
    SELECT
        document_id,
        argMax(metadata.source_product, inserted_at) as source_product,
        argMax(metadata.source_product, inserted_at) as source_product,
        argMax(metadata.source_type, inserted_at) as source_type,
        argMax(metadata.deleted, inserted_at) as deleted,
        argMax(timestamp, inserted_at) as signal_ts
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
      AND product = 'signals'
      AND document_type = 'signal'
      AND timestamp >= now() - INTERVAL 1 MONTH
    GROUP BY document_id
)
WHERE deleted != 'true'
GROUP BY source_product, source_type
ORDER BY latest_timestamp DESC
LIMIT 100
```

## Example 4: Recent Signals from a Specific Source

Find the latest signals from a particular product source (e.g. all error tracking signals):

```sql
SELECT
    document_id,
    content,
    source_type,
    report_id,
    signal_ts
FROM (
    SELECT
        document_id,
        argMax(content, inserted_at) as content,
        argMax(metadata.source_product, inserted_at) as source_product,
        argMax(metadata.source_type, inserted_at) as source_type,
        argMax(metadata.report_id, inserted_at) as report_id,
        argMax(metadata.deleted, inserted_at) as deleted,
        argMax(timestamp, inserted_at) as signal_ts
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
      AND product = 'signals'
      AND document_type = 'signal'
      AND timestamp >= now() - INTERVAL 1 WEEK
    GROUP BY document_id
)
WHERE source_product = 'error_tracking'
  AND deleted != 'true'
ORDER BY signal_ts DESC
LIMIT 100
```

Replace `'error_tracking'` with any source product: `'web_analytics'`, `'experiments'`, `'session_replay'`, etc. Use Example 3 to discover what source products and types exist.

## Example 5: Full-Text Search for Signals

When you know a specific keyword or phrase to search for (e.g. a product name, error message, or URL), full-text search with `ILIKE` is faster and more precise than semantic search:

```sql
SELECT
    document_id,
    content,
    source_product,
    source_type,
    signal_ts
FROM (
    SELECT
        document_id,
        argMax(content, inserted_at) as content,
        argMax(metadata.source_product, inserted_at) as source_product,
        argMax(metadata.source_type, inserted_at) as source_type,
        argMax(metadata.deleted, inserted_at) as deleted,
        argMax(timestamp, inserted_at) as signal_ts
    FROM document_embeddings
    WHERE model_name = 'text-embedding-3-small-1536'
      AND product = 'signals'
      AND document_type = 'signal'
      AND timestamp >= now() - INTERVAL 1 MONTH
    GROUP BY document_id
)
WHERE deleted != 'true'
  AND content ILIKE '%feature flag%'
ORDER BY signal_ts DESC
LIMIT 10
```

Replace `'%feature flag%'` with whatever term you're looking for. Use `ILIKE` for case-insensitive substring matching. For exact token matching, use `hasTokenCaseInsensitive(content, 'token')` instead.

## Gotchas

1. **Always use `text-embedding-3-small-1536` as the model name.** This is the only model used for signals.
2. **`embedText()` arguments must be string literals.** You cannot pass column references or expressions — the function resolves at compile time, not per row.
3. **Always time-bound your queries.** The table has a 3-month TTL, but unbounded scans are expensive. Use `timestamp >= now() - INTERVAL 1 MONTH` or tighter. Place the time filter in the inner subquery's `WHERE` clause (on the raw `timestamp` column) for best performance.
4. **Always deduplicate.** Without the `argMax(..., inserted_at) GROUP BY document_id` subquery, you will see stale and duplicate rows.
5. **Only select `embedding` when you need it.** It's a 1536-element float array — omit it from the inner subquery when you're not doing similarity search.
6. **Queries should not end with a semicolon.** HogQL does not use them.
7. **Add a `LIMIT` to every query.** Maximum allowed is 500 rows. In general, you should only select 10 or so signals, using semantic or full text search to rank them.
8. **Extract metadata fields inside the dedup subquery.** HogQL's `metadata.field` dot access only works on the raw table column. After `argMax()` aggregation, the JSON type is lost and dot access will fail with a type error. Always use `argMax(metadata.field_name, inserted_at) as field_name` in the inner query.
9. **All JSON dot-access values are `Nullable(String)`.** HogQL extracts every JSON field as a String, even booleans and numbers. For `metadata.deleted`, use `deleted != 'true'` — do NOT use `NOT deleted`.
10. **Don't alias `argMax(timestamp, inserted_at)` as `timestamp` if the same inner query also filters on the raw `timestamp` column.** HogQL resolves the alias name first, causing an "aggregate in WHERE" error. Either use a distinct alias like `signal_ts`, or move the time filter to the outer query.
