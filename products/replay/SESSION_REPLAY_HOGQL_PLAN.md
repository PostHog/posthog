# `session_replay_events` HogQL rework plan

Working doc. Delete once PRs land.

## Problem

`session_replay_events` in HogQL is misleading:

- `raw_session_replay_events` → row-per-CH-state-part (an `AggregatingMergeTree` implementation detail, not "raw events"). Cardinality per session is undefined.
- `session_replay_events` → lazy `GROUP BY session_id` view over the above. Intended to give one row per session.

Users writing `SELECT count() FROM session_replay_events` might think they're counting events. They're counting sessions. Worse, the grouped view is itself buggy.

## Bugs in the current grouped view (`SessionReplayEventsTable`)

Confirmed by reading the ClickHouse DDL in `posthog/session_recordings/sql/session_replay_event_sql.py`:

1. **`AggregateFunction(argMin, ...)` columns exposed as plain strings.** `first_url`, `snapshot_source`, `snapshot_library` are `AggregateFunction` state in CH. The HogQL schema declares them as `StringDatabaseField` / `DatabaseField`, so reading them without `argMinMerge` returns state-byte blobs. `first_url` gets `argMinMerge` in the lazy view — but `snapshot_source` and `snapshot_library` don't.
2. **Fields that leak into `GROUP BY`, splitting sessions.** `snapshot_source`, `snapshot_library`, `retention_period_days` are in `SESSION_REPLAY_EVENTS_COMMON_FIELDS` with no aggregation. The lazy-view generator adds any requested-but-not-aggregated field to the `GROUP BY` clause, so a session with state parts that disagree on (e.g.) `retention_period_days` splits into multiple rows. Contract violation: "grouped view = one row per session".
3. **Nondeterministic `distinct_id`.** `any(distinct_id)` — a session can have multiple distinct_ids (identify / alias). Decision: pick latest (by `max_last_timestamp`) so a session that starts anonymous and then identifies resolves to the identified distinct_id. Best-effort: once ClickHouse merges state parts in the background, `distinct_id` (a plain VARCHAR) is collapsed by `any` at the storage layer, so for old sessions we get whatever CH picked. Acceptable — in that case distinct_ids for the session have usually converged anyway.
4. **`is_deleted` semantics.** `max(is_deleted)` = "any state part deleted ⇒ session deleted". Probably right (matches the CH column's own `SimpleAggregateFunction(max)`), but worth a test.
5. **Duplicate-ingestion double-counting risk.** CH merges state parts asynchronously; `sum(click_count)` over state parts is correct because each part carries a partial sum. But if the same ingestion batch lands twice in Kafka, `sum` double-counts. This is a broader ingestion concern, not HogQL's job to fix — but the tests should document behaviour.

## Bugs in `raw_session_replay_events`

1. **Same `AggregateFunction` columns as above** — `first_url`, `snapshot_source`, `snapshot_library` are exposed as plain strings. Reading them returns state blobs. Worse here because there's no `argMinMerge` _anywhere_.
2. **Name promises something the data doesn't deliver.** "Raw" suggests row-per-event. The storage is row-per-state-part. Undefined cardinality makes any aggregation unreliable unless the user writes their own `GROUP BY session_id`.

## Open question before PR5 (the flip)

Given (2) above, does flipping `session_replay_events` to point at the raw table actually help users? The raw table isn't a correct row-per-event view — no such view exists.

Two directions:

- **A. Keep user's original instinct.** Flip names: `session_replay_events` = raw state parts, `grouped_session_replay_events` = correct one-row-per-session. Pro: table name matches CH table name. Con: users writing naive queries against `session_replay_events` still get confusing cardinality.
- **B. Only expose the grouped view under `session_replay_events`.** Treat `raw_session_replay_events` as an advanced/debug hatch that we don't migrate users to. Pro: the default name gives the right answer. Con: can't trivially see state-part granularity from HogQL.

I lean B, but it's your call. Doesn't block PR 1–3.

## Plan (six PRs, each independently shippable)

### PR 1 — spec tests for `grouped_session_replay_events`

New test file `posthog/hogql/database/schema/test/test_grouped_session_replay_events.py` that pins the correct contract for a one-row-per-session view. The whole module is gated by `pytest.mark.skipif(not _grouped_table_registered())`, which inspects `ROOT_TABLES__DO_NOT_ADD_ANY_MORE` for `"grouped_session_replay_events"`. Tests skip today and auto-enable the moment PR 2 registers the table — no coordination between PRs required, no risk of silent re-passing if someone later regresses.

Also extends `posthog/session_recordings/queries/test/session_replay_sql.py` with `event_count`, `message_count`, `ai_tags_fixed`, `ai_tags_freeform`, `ai_highlighted` so the helper writes the columns the test file needs.

Scenarios covered in the committed file:

- **Cardinality contract.** Given N state parts for one session, the view returns exactly one row — including when state parts disagree on `snapshot_source` / `snapshot_library` / `retention_period_days` / `is_deleted` / `distinct_id` / repeated URLs / AI tags.
- **`first_url` / `snapshot_source` / `snapshot_library`** — earliest value as a readable string, not an `AggregateFunction` state blob.
- **`all_urls`** — union across parts, deduped across repeated URLs.
- **Count aggregations** — `click_count`, `keypress_count`, `mouse_activity_count`, `active_milliseconds`, `console_log_count`, `console_warn_count`, `console_error_count`, `size`, `event_count`, `message_count` each sum across parts. Expected values derived from `PARTS × PER_PART_X` named constants so setUp and assertions stay consistent.
- **`start_time` / `end_time`** — min/max across parts.
- **`is_deleted`** — any part deleted ⇒ session deleted.
- **`distinct_id`** — latest by `max_last_timestamp` wins; caveat documented inline (best-effort once CH merges state parts).
- **`retention_period_days`** — max across parts.
- **`ai_tags_fixed` / `ai_tags_freeform`** — deduped union.
- **`ai_highlighted`** — any part highlighted ⇒ session highlighted.
- **Team scoping** — two teams producing state parts for the same session_id do not pollute each other's row. Other team's sessions are invisible.
- **Lazy join smoke** — `events.event` resolves through the grouped view.
- **`SELECT *`** — returns one row with the expected columns.

### PR 2 — implement `grouped_session_replay_events`

New class, registered additively in `database.py`. Not a refactor of `SessionReplayEventsTable`. Written fresh against the tests from PR 1. Leaves existing tables alone.

Key implementation notes:

- Separate "fields visible in the grouped view" from "fields that happen to exist on the raw state-part table". No shared `COMMON_FIELDS` dict.
- Every field must either be aggregated in the lazy view or be `session_id` / `team_id`. No field can silently leak into `GROUP BY`.
- `first_url`, `snapshot_source`, `snapshot_library` use `argMinMerge`.

### PR 3 — audit internal callers (read-only report)

For every code reference to either table, classify correct / wrong / ambiguous. Output is a markdown report, not a diff. Any wrong/ambiguous cases become separate follow-up tickets — not blocking this rename.

### PR 4 — migrate saved user queries

Django data migration. For every JSONField holding user HogQL (`Insight.query`, `DataWarehouseSavedQuery.query`, plus anything else discovered by grepping Django models for embedded HogQL), parse with `posthog.hogql.parser.parse_select`, AST-rewrite `session_replay_events` → `grouped_session_replay_events`, print back. **No string replace.**

Edge cases:

- Unparsable query → skip, log.
- Already references `grouped_session_replay_events` → no-op.
- Non-HogQL fields that happen to contain the substring → skip (AST parse will fail and we skip).

### PR 5 — flip `session_replay_events` (or don't — see open question)

**First, measure.** Before flipping anything, sample real usage: how often does `session_replay_events` appear in saved HogQL today (Insight, DataWarehouseSavedQuery, Experiment, Alert, HogFunction inputs), and what shapes of queries run through `/api/query`? Direction A and B both have tradeoffs; a cheap read-only audit is the difference between "probably right" and "knowing what we'd break".

If we go with direction A: point `session_replay_events` at the raw table, keep `raw_session_replay_events` as a compat alias.

If we go with direction B: leave `session_replay_events` pointing at the correctly-grouped view (which now is `grouped_session_replay_events` under the hood), deprecate `raw_session_replay_events` but keep it working.

### PR 6 — docs, skills, examples

- `products/posthog_ai/skills/query-examples/references/hogql-extensions.md` example.
- AGENTS.md guidance if any.
- SQL editor example queries in-app.

## Constraints (from conversation)

- The pre-grouped view must hide all grouping complexity. One row per session, always. No GROUP BY surprises.
- Don't copy the existing `SessionReplayEventsTable` implementation — we think it's wrong. Rebuild from tests.
- Don't migrate internal callers in the same PR that audits them. Audit is read-only.
- Don't migrate `Insight.query` / `DataWarehouseSavedQuery.query` via string replace. Always AST.
