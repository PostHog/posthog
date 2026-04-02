# ai_events table rollout

## Overview

Dedicated ClickHouse table for AI events with extracted columns
(trace IDs, tokens, costs, latency, heavy I/O data).
30-day TTL with partition-level expiration.

## Architecture

- **Write side** (Node.js): `split-ai-events-step.ts`, gated by env vars
- **Read side** (Python): query runners, gated by `ai-events-table-rollout` feature flag
- **MV**: populates ai_events from dedicated Kafka topic (`clickhouse_ai_events_json`)

## Env vars

| Var                                        | Default | Purpose                                 |
| ------------------------------------------ | ------- | --------------------------------------- |
| `INGESTION_AI_EVENT_SPLITTING_ENABLED`     | `false` | Master switch for dual-writing          |
| `INGESTION_AI_EVENT_SPLITTING_TEAMS`       | `*`     | Team allowlist (`*` or comma-separated) |
| `INGESTION_AI_EVENT_SPLITTING_STRIP_HEAVY` | `false` | Strip heavy props from `events` copy    |

## Feature flag

`ai-events-table-rollout` -- per team ID, controls read-side table routing.

## Rollout phases

### Phase 1: Deploy code (all gates OFF)

- Feature flag defaults OFF
- All env vars at defaults (splitting disabled)
- Zero behavior change from current production

### Phase 2: Enable double-write for test team

```bash
INGESTION_AI_EVENT_SPLITTING_ENABLED=true
INGESTION_AI_EVENT_SPLITTING_TEAMS=<llma_team_id>
INGESTION_AI_EVENT_SPLITTING_STRIP_HEAVY=false   # keep heavy props in events
```

- `events` keeps full data (unchanged)
- `ai_events` also gets full data
- Fully reversible: set `ENABLED=false`, zero impact

### Phase 3: Enable reads for test team

- Enable `ai-events-table-rollout` flag for LLMA team ID
- Query runners + evaluation_runs switch to ai_events
- Verify: traces page, errors tab, tools tab, evaluation triggers
- Fully reversible: disable flag -> reads revert to `events` (which has full data)

### Phase 4: CH team backfills last 30 days

- ai_events gets historical data populated
- Verify: date ranges beyond phase 2 show data correctly

### Phase 5: Expand and flip reads for everyone

- Expand env var teams + feature flag to more teams, then all
- Monitor query latency and data completeness
- Once stable: set `STRIP_HEAVY=true` -> events stops getting heavy props
- CH team is free to rewrite `events` history to drop heavy columns

### Phase 6: Cleanup (see section below)

## Rollback at any phase

### Phase 2 rollback (writes only, no stripping)

Set `INGESTION_AI_EVENT_SPLITTING_ENABLED=false`.
events was never modified -> zero impact.

### Phase 3 rollback (reads enabled, no stripping)

Disable `ai-events-table-rollout` feature flag.
All reads revert to `events` which has complete data -> zero impact.

### Phase 5 rollback (pre-stripping)

Same as phase 3 -- disable flag, reads revert, events has full data.

### Phase 5 rollback (post-stripping enabled)

1. Disable feature flag -> reads revert to events
2. Set `STRIP_HEAVY=false` -> new events get full data in events again
3. Events written during the stripping window have stripped heavy props
   in `events`, but ai_events has full data for those.
   Re-enable the flag if you need to serve that data from ai_events.

### Full rollback from any pre-stripping phase

1. Disable feature flag (instant)
2. Set `ENABLED=false`
3. System is back to pre-rollout state, zero data loss

## Code cleanup after GA

After stable GA and CH team has rewritten events history:

### Python read side

- [ ] Remove `is_ai_events_enabled()` from `ai_table_resolver.py`
- [ ] Remove `posthoganalytics` import from `ai_table_resolver.py`
- [ ] Remove feature flag guard from `_should_use_ai_events_table()` in all 4 runners
      (method becomes just the TTL check)
- [ ] Remove events-path from `evaluation_runs.py` (keep only ai_events path)
- [ ] Extract `_enrich_persons()` from `ai_events_query_runner.py` into a shared utility
      and remove the duplicate from `EventsQueryRunner._calculate()`
- [ ] Delete feature flag `ai-events-table-rollout` from PostHog
- [ ] Remove test mocks for `posthoganalytics.feature_enabled`

### Node.js write side

- [ ] Remove `INGESTION_AI_EVENT_SPLITTING_STRIP_HEAVY` env var
      (stripping becomes unconditional, or unnecessary if CH MV strips)
- [ ] Remove `INGESTION_AI_EVENT_SPLITTING_TEAMS` env var
      (splitting applies to all teams)
- [ ] Simplify `SplitAiEventsStepConfig` to just `enabled: boolean`
- [ ] If CH team changes events MV to exclude heavy props at the table level,
      remove stripping logic from `maybeStripAiProperties()` entirely
      (just duplicate unchanged to both outputs)

### Stays permanently

- `AiColumnToPropertyRewriter` -- needed for TTL fallback (queries >30 days)
- `AiPropertyRewriter` + `AI_PROPERTY_TO_COLUMN` -- needed for HogQL property->column rewriting
- `merge_heavy_properties()` + `HEAVY_COLUMN_TO_PROPERTY` -- needed by evaluation_runs.py
- `INGESTION_AI_EVENT_SPLITTING_ENABLED` -- keep as kill switch
- ai_events table definition, MV, Kafka topic
- HogQL `AiEventsTable` schema
- All test utilities (`bulk_create_ai_events`, etc.)
