# Task search and custom feeds

## Status

This document proposes a search and saved-feed architecture for Tasks.

## Summary

Tasks already has a permission-aware PostgreSQL search projection.
It supports exact task, pull request, artifact, and space matches for the Desktop command menu.
It does not support semantic search, structured search filters, or saved feeds.

The repository also contains an OpenSearch proof of concept for AI observability traces.
It is not a shared application search service yet.
The Temporal Elasticsearch service is not suitable for product data.

The recommended approach is:

1. Extend the existing PostgreSQL task search projection for lexical search and structured filters.
2. Store custom feeds as saved, versioned task queries in PostgreSQL.
3. Reuse the shared embedding pipeline and `document_embeddings` table for semantic candidates.
4. Rejoin every candidate to PostgreSQL before returning it.
5. Add an OpenSearch backend only when measured scale or latency requires it.

This approach ships useful feeds without adding a new production dependency.
It also keeps an explicit path to OpenSearch.

## Goals

- Find tasks by title, description, task number, slug, repository, pull request, artifact name, and space.
- Find tasks by topic when the query and task use different words.
- Filter tasks by creator, space, repository, origin, run status, pull request state, CI state, archive state, and date.
- Save a query as a personal or team feed.
- Support examples such as "my tasks", "tasks about data warehouse", and "my tasks with an open pull request and failing CI".
- Keep search results and feeds within the existing task visibility rules.
- Keep the index rebuildable from authoritative product data.
- Return current task data rather than treating a search document as the source of truth.

## Non-goals

- Full-text search over run logs, artifact contents, comments, or Canvas source code.
- A replacement for channel feeds or the Activity feed.
- Notification delivery for every matching feed change.
- A generic search platform for every PostHog product in the first release.

## What exists today

### Task list search

`GET /api/projects/{id}/tasks/` supports a case-insensitive title and description substring filter.
It also supports creator, repository, origin, space, archive state, and latest-run status filters.
The implementation is in `products/tasks/backend/facade/api.py`.

This endpoint returns task cards and has the correct task visibility boundary.
It does not provide relevance ranking or semantic search.

### Task command-menu search

`TaskSearchDocument` is a team-scoped, rebuildable PostgreSQL projection.
It has documents for tasks, pull requests, artifacts, and spaces.
The projection stores exact identifiers and normalized search text.
GIN indexes support exact array matches and trigram text matches.

`products/tasks/backend/search_index.py` updates the projection after task, run, artifact, and space writes.
The search endpoint ranks exact identifiers before prefix and substring matches.
Desktop merges these remote results with its local task results in Cmd+K.

This is the best base for the first release.
It already handles environment canonicalization, resource navigation, deletion, backfill, and personal-space visibility.

### OpenSearch

`products/ai_observability/opensearch/` contains a local OpenSearch service and an `llm-traces` index template.
Its README describes a reverse-index proof of concept for AI observability traces.
The README also says production uses managed AWS OpenSearch Service through infrastructure code outside this repository.
The Tasks development intent does not start this service.

The managed domain is worth evaluating as shared infrastructure.
However, the current tree does not contain a merged task writer, task query client, or shared search contract for OpenSearch.
The trace template is also unsuitable for tasks because it has trace-specific fields and lifecycle rules.

OpenSearch can become a backend for this design, but Tasks cannot reuse the current trace index directly.
At minimum, Tasks needs a separate mapping, read and write aliases, an exhaustive writer, query code, access controls, deletion handling, and production capacity ownership.

### Temporal Elasticsearch

The `elasticsearch` service in the development stack is configured as Temporal's visibility store.
Temporal owns its schema and lifecycle.
Tasks must not write product documents into that cluster or query its internal indexes.

### Elasticsearch data warehouse source

PostHog can import data from an external Elasticsearch cluster into the data warehouse.
That connector is an ingestion source.
It is not an application search backend.

### Shared semantic-search infrastructure

PostHog already has a shared embedding path:

```text
product code
  -> emit_embedding_request()
  -> document_embeddings_input Kafka topic
  -> embedding worker
  -> model-specific ClickHouse document_embeddings table
```

`products/business_knowledge/backend/logic.py` already combines PostgreSQL full-text search with ClickHouse vector candidates.
It uses reciprocal rank fusion, rejoins candidates to PostgreSQL, and falls back to lexical search when embedding generation fails.

This pattern is suitable for task-topic search.
The shared embedding tables have a three-month TTL.
Long-lived task search therefore needs periodic re-emission before vectors expire.

## Main design decision

Use one task-grain search document as the query and feed unit.
Keep the existing pull request, artifact, and space documents as navigational aliases for global search.

A search for an artifact can still open its containing task.
A custom feed returns each task once, even when several related resources match.

PostgreSQL remains authoritative for:

- tenant and user visibility,
- structured filters,
- current task and run state,
- saved-feed definitions,
- pagination and hydration.

The semantic index returns candidate task IDs and scores only.
It never grants access and never returns a complete task response.

## Search projection

Extend the existing `kind="task"` row in `TaskSearchDocument` with first-class task fields.
Do not put filterable fields only in `metadata`.
First-class columns give PostgreSQL useful indexes and a typed query contract.

Suggested fields for task documents:

| Field                  | Purpose                                                   |
| ---------------------- | --------------------------------------------------------- |
| `task_id`              | Stable task identity and hydration key                    |
| `team_id`              | Tenant boundary                                           |
| `channel_id`           | Space filter and visibility input                         |
| `created_by_id`        | Creator and "my tasks" filter                             |
| `origin_product`       | Task-origin filter                                        |
| `repositories`         | Repository filter                                         |
| `latest_run_id`        | Current run identity                                      |
| `latest_run_status`    | Current run-status filter                                 |
| `pr_urls`              | Exact pull request lookup                                 |
| `pr_state`             | `none`, `draft`, `open`, `merged`, `closed`, or `unknown` |
| `ci_state`             | `none`, `pending`, `passing`, `failing`, or `unknown`     |
| `pr_status_updated_at` | Freshness and reconciliation input                        |
| `archived`             | Archive filter                                            |
| `internal`             | Default exclusion and staff behavior                      |
| `task_created_at`      | Date filter and stable sort                               |
| `activity_at`          | Recent-activity sort                                      |
| `search_text`          | Normalized text for trigram and fallback matching         |
| `search_vector`        | Weighted PostgreSQL full-text vector                      |
| `content_version`      | Idempotent update and embedding version                   |
| `embedding_emitted_at` | Embedding reconciliation and TTL refresh                  |

The lexical document should include bounded values from:

- task title,
- task description,
- task slug and number,
- repository names,
- related pull request URLs and numbers,
- active artifact names,
- space name.

Weight the title and exact identifiers above the description.
Use artifact names and repository names as lower-weight context.
Do not include run logs, artifact bodies, comments, credentials, or Canvas source code.

A Canvas name can become a separate global-search alias later.
Canvas should write that alias through a small Tasks facade instead of making Tasks import Canvas models.
A Canvas without a bound task should not appear in a task feed.

## Index update flow

PostgreSQL models remain the source of truth.
The search projection is disposable and rebuildable.

```text
Task, TaskRun, TaskArtifact, Channel, or PR-state change
  -> database transaction commits
  -> enqueue coalesced update for (canonical_team_id, task_id)
  -> load current source rows
  -> build one complete task document
  -> idempotent upsert by (team_id, kind, source_key)
  -> emit a new semantic document only when semantic content changed
```

Use a complete-document upsert instead of patches from each event.
This avoids ordering bugs when updates arrive close together.
A `content_version` hash can make stale jobs harmless.

The current synchronous `transaction.on_commit` updater is acceptable during the first iteration.
Move projection work to a retrying worker when write latency or update volume becomes material.
Coalesce repeated task updates before the worker rebuilds the document.

Keep a periodic reconciliation job and the existing rebuild command.
The job should compare source counts, missing task IDs, and stale projection versions.
This repairs updates lost during broker or worker failures.

### Pull request and CI state

The existing GitHub snapshot code already computes `pr_state` and `ci_status` in `get_pr_context`.
Persist those values into the task projection when that snapshot succeeds.

The pull request webhook already resolves a pull request to a task run for opened and closed events.
Extend that path to enqueue a projection refresh for supported state changes.
Add GitHub check and status event handling if the installed GitHub App receives those events.

Use a slow reconciliation poll for open pull requests when webhook delivery or personal GitHub credentials cannot provide complete coverage.
Only refresh stale open pull requests.
Store `pr_status_updated_at` so the API can report or measure stale state.

Do not call GitHub once per task during a feed request.
Feed reads must use indexed state.

## Query contract

Use one versioned query object for ad hoc search and saved feeds.
Do not store raw PostgreSQL, HogQL, or OpenSearch syntax.

Example:

```json
{
  "version": 1,
  "text": "data warehouse",
  "mode": "hybrid",
  "filters": {
    "created_by": { "kind": "current_user" },
    "repositories": ["posthog/posthog"],
    "latest_run_status": ["completed"],
    "pr_state": ["open", "draft"],
    "ci_state": ["failing"],
    "archived": false
  },
  "sort": "relevance"
}
```

Supported sort values should start with:

- `relevance`,
- `activity_desc`,
- `created_desc`,
- `updated_desc`.

Resolve `current_user` at read time.
A fixed creator filter should store an explicit user ID.
The UI must make this difference clear when a team feed is shared.

Use opaque keyset cursors.
Include the selected sort value and task ID in the cursor.
Relevance results can change when the index changes, so they do not provide snapshot pagination.

## Query execution

### Structured and lexical path

1. Resolve the requester and canonical team.
2. Build the visible task queryset with the existing visibility helper.
3. Apply structured filters to `kind="task"` projection rows.
4. Rank exact identifiers first.
5. Rank PostgreSQL full-text matches next.
6. Use trigram similarity for partial and typo-tolerant fallback matches.
7. Hydrate matching task IDs from the authoritative task query.
8. Recheck visibility during hydration.

Search must work when the query has no text.
This is how feeds such as "my tasks with failing CI" avoid unnecessary semantic work.

### Hybrid semantic path

Run semantic search only when the query has text, the mode is `hybrid`, and the organization permits AI data processing.

1. Generate a query embedding with `text-embedding-3-small-1536`.
2. Query `document_embeddings` with `product="tasks"` and `document_type="task"`.
3. Over-fetch semantic task IDs and cosine distances.
4. Fuse semantic and lexical ranks with reciprocal rank fusion.
5. Rejoin IDs to filtered, visible PostgreSQL projection rows.
6. Hydrate current task data from PostgreSQL.
7. Fall back to lexical results when the embedding service or ClickHouse is unavailable.

The semantic document should contain the title and a bounded task description.
It should not include status fields because status changes do not change a task's topic.

The ClickHouse table expires vectors after three months.
Mirror the Business knowledge refresh pattern:

- mark successful emissions with `embedding_emitted_at`,
- reconcile old emissions against ClickHouse,
- re-emit vectors after about 60 days,
- use a fresh timestamp for old tasks and refreshes,
- rejoin to PostgreSQL so duplicate or stale vector rows cannot surface deleted tasks.

A narrow structured filter can discard many semantic candidates after the rejoin.
Start with bounded over-fetch and record the discarded-candidate rate.
If valid pages often remain under-filled, increase candidates within a hard cap.
This metric is also a useful signal for an OpenSearch migration.

## Saved feeds

A custom feed is a saved task query.
It is not a materialized list of task IDs.
The query runs when a user opens the feed, so status changes appear without per-feed fanout writes.

Suggested model:

```text
TaskFeed
  id
  team_id
  name
  created_by_id
  visibility: personal | team
  query_version
  query_json
  created_at
  updated_at
```

The model must use the fail-closed team-scoped manager.
A personal feed is visible only to its creator.
A team feed is visible to project members, but its results still use each requester's task visibility.

Suggested endpoints:

```text
POST   /api/projects/{id}/task_search/query
GET    /api/projects/{id}/task_feeds
POST   /api/projects/{id}/task_feeds
GET    /api/projects/{id}/task_feeds/{feed_id}
PATCH  /api/projects/{id}/task_feeds/{feed_id}
DELETE /api/projects/{id}/task_feeds/{feed_id}
GET    /api/projects/{id}/task_feeds/{feed_id}/results
```

The create endpoint must validate the complete query object.
The results endpoint should call the same query service as ad hoc search.

Built-in feeds do not need database rows.
The client can provide presets for:

- My tasks.
- Created by me with an open pull request.
- Created by me with failing CI.
- Recently active tasks.

A user can copy a preset into a saved feed and change its filters.

Do not add unread counts or notifications in the first release.
Those features require change evaluation and delivery rules, not only a search query.
If notifications are added later, build a separate matcher that evaluates changed tasks against eligible feed definitions.

## Authorization and privacy

Search is not an authorization boundary.
Every request must begin with or rejoin through the existing visible-task queryset.

Required rules:

- Always constrain by canonical `team_id`.
- Preserve personal-space ownership checks.
- Preserve null-space legacy visibility rules.
- Exclude internal tasks by default.
- Recheck visibility after semantic or OpenSearch candidate retrieval.
- Return IDs from external indexes, then hydrate from PostgreSQL.
- Delete or tombstone index entries when a task or team is deleted.
- Never accept raw search-engine syntax from a client.

Semantic indexing sends task text through the existing embedding service.
Honor the organization's AI data-processing setting.
Keep the semantic document bounded and exclude logs, comments, artifact bodies, and secrets.

A deleted task can remain in ClickHouse until a mutation or TTL removes its vector.
The PostgreSQL rejoin prevents that vector from becoming a visible result.
A compliance deletion flow should also remove or tombstone its semantic rows.

## When to use OpenSearch

OpenSearch becomes useful when at least one of these conditions is measured:

- PostgreSQL search latency misses the agreed target at expected team sizes.
- Hybrid queries need structured filters inside vector retrieval to fill pages reliably.
- Fuzzy matching, highlighting, facets, or ranking rules become too complex for PostgreSQL.
- Index write volume causes material load on the primary PostgreSQL database.
- Several products commit to a shared search service with production ownership.

Do not migrate only because OpenSearch exists in the development stack.

### OpenSearch task index

Use a dedicated versioned index and aliases, such as:

```text
tasks-v1-000001
tasks-search-read
tasks-search-write
```

Store one exhaustive document per task.
Do not sample tasks because missing task results would break feeds.

Suggested mapping groups:

- `keyword`: `team_id`, `task_id`, creator, origin, repositories, run status, pull request state, CI state, visibility keys.
- `date`: created, updated, activity, and pull request status timestamps.
- `text`: title, description, artifact names, and normalized identifiers.
- `knn_vector`: task-topic embedding, if OpenSearch owns semantic retrieval.

The query layer must add team and visibility filters through a required server-side builder.
Clients must never send OpenSearch DSL.
The OpenSearch security plugin is disabled in local development, so application filters remain mandatory in every environment.

The writer should consume compact task-document updates from a durable outbox or Kafka topic.
It should use idempotent document IDs, bulk writes, retries, a dead-letter path, and lag metrics.
The event-ingestion-specific trace indexer is not directly reusable, but its bulk retry and health patterns can guide a shared library.

### Migration path

Keep a backend interface even while PostgreSQL is the only implementation:

```text
TaskSearchBackend.search(query, viewer, cursor) -> candidate task IDs and scores
TaskSearchBackend.upsert(document)
TaskSearchBackend.delete(team_id, task_id)
```

Use this rollout sequence:

1. Create the OpenSearch mapping and aliases.
2. Backfill from PostgreSQL in bounded team batches.
3. Dual-write PostgreSQL and OpenSearch.
4. Shadow-read OpenSearch and compare result overlap, visibility, latency, and empty-result rates.
5. Enable OpenSearch reads for selected teams.
6. Keep PostgreSQL lexical fallback during the rollout.
7. Remove the old path only after reconciliation and deletion checks are stable.

A shared OpenSearch domain still needs separate indexes, IAM permissions, capacity budgets, and ownership between products.
Sharing a domain does not mean sharing the trace index or its sampling policy.

## Failure behavior

| Failure                                       | Expected behavior                                                       |
| --------------------------------------------- | ----------------------------------------------------------------------- |
| Projection update fails                       | Retry or repair through reconciliation; the source write still succeeds |
| Embedding service fails                       | Return lexical results                                                  |
| ClickHouse vector query fails                 | Return lexical results                                                  |
| GitHub status refresh fails                   | Keep the last state, record freshness, and retry later                  |
| OpenSearch fails during a future rollout      | Fall back to PostgreSQL while the fallback remains enabled              |
| Candidate references a deleted or hidden task | Drop it during PostgreSQL rejoin                                        |
| Saved query uses an unknown version           | Return a validation error and do not run it                             |

## Observability and targets

Record these metrics before changing backends:

- lexical and hybrid query latency,
- query result count and empty-result rate,
- projection update lag,
- source-to-projection count difference,
- embedding coverage and age,
- semantic candidate discard rate after PostgreSQL filters,
- lexical fallback rate,
- stale pull request and CI state count,
- clicked result rank,
- saved-feed creation and repeat-open rates.

Initial service targets:

- p95 structured or lexical feed load below 500 ms at the API.
- p95 projection freshness below 10 seconds after a source commit.
- p95 pull request and CI freshness below 60 seconds after a supported webhook.
- Zero results that fail the authoritative visibility check.

Measure real team sizes and query patterns before setting an OpenSearch cutover threshold.

## Delivery plan

### Phase 1: structured search and feeds

- Add first-class structured fields to task search documents.
- Build complete task documents from current source rows.
- Add full-text ranking and trigram fallback.
- Persist pull request and CI snapshots.
- Add the versioned search query service.
- Add personal saved feeds.
- Add cursor pagination and result hydration.

This phase supports "my tasks" and "my tasks with an open pull request and failing CI".

### Phase 2: semantic topics

- Emit bounded task-topic documents through the shared embedding pipeline.
- Add reconciliation and 60-day refresh.
- Add hybrid retrieval and lexical fallback.
- Add semantic coverage and relevance metrics.

This phase supports "all tasks about this topic".

### Phase 3: sharing and product refinements

- Add team-visible feeds.
- Add built-in presets and feed management UI.
- Add Canvas aliases through a cross-product facade.
- Evaluate notifications as a separate design.

### Phase 4: optional OpenSearch backend

- Confirm a measured PostgreSQL or hybrid-retrieval limit.
- Establish production ownership and capacity.
- Build the dedicated task index and exhaustive writer.
- Dual-write, shadow-read, and roll out by team.

## Open questions

- Should shared feeds resolve `current_user` per viewer, or should shared feeds require fixed creator IDs?
- How old can pull request and CI state be before the UI marks it stale?
- Should semantic search include the latest bounded agent summary, or only the user-authored task description?
- What task count and query rate should trigger the OpenSearch phase?
- Do custom feeds need notifications, or is an on-demand saved view sufficient?
