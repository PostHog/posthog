---
name: finding-deleted-feature-flags
description: 'Find feature flags that were soft-deleted in the active project within a recent time window. Use when the user asks "what flags were deleted in the last N days", "show me recently deleted feature flags", "who deleted flag X", "audit recent flag deletions", or anything similar. Handles the non-obvious gotcha that system.feature_flags exposes the deleted boolean but does not expose a deletion timestamp — the actual deleted-at time lives in the per-flag activity log and must be cross-referenced.'
---

# Finding recently deleted feature flags

This skill produces a list of feature flags that were soft-deleted in the active project within a user-specified time window, along with who deleted each one and when.

## When to use this skill

- The user asks "what flags got deleted last week / in the last N days?"
- The user wants an audit of recent flag deletions (who, when, what was removed)
- The user wants to find when a specific flag was deleted, or by whom
- Any "recently deleted feature flags" framing

Don't use this for **active** stale-flag cleanup — that's `cleaning-up-stale-feature-flags`. This skill is for flags that have already been removed.

## The gotcha that makes this non-trivial

`system.feature_flags` exposes `deleted` as a boolean but does **not** expose `deleted_at`, `updated_at`, or `last_modified_at`. There's no way to filter soft-deleted flags by deletion time in a single SQL query — trying to use those columns will return `Unable to resolve field`.

The actual deletion timestamp lives in the per-flag activity log, reachable only via `posthog:feature-flags-activity-retrieve` (one call per flag id). There is no bulk activity endpoint.

So the workflow is two-stage: SQL to enumerate candidates, then parallel activity-log lookups to find each deletion event.

## Workflow

### 1. Clarify the window if ambiguous

"Last week" is ambiguous — it can mean rolling 7 days from now, or the previous calendar week (Mon–Sun). If the user wasn't explicit, ask, or surface both interpretations in the final report.

Always compute the cutoff in UTC and keep the user's local interpretation in your head separately.

### 2. Enumerate soft-deleted flags via SQL

Query `system.feature_flags` for `deleted = true` in the active project, ordered by `created_at DESC`:

```sql
SELECT id, key, created_at
FROM system.feature_flags
WHERE team_id = <team_id> AND deleted = true
ORDER BY created_at DESC
LIMIT 100
```

Order by `created_at DESC` because deletions empirically cluster near creation — most flags get deleted within a few days of being created — so walking the most-recently-created candidates first finds recent deletions fastest. **But** this is a heuristic, not a guarantee: an older flag deleted recently won't be at the top of this list. Be explicit about that limitation when you report.

`team_id` defaults to the active project, but include it explicitly for clarity.

### 3. Fan out activity-log lookups in parallel

For each candidate id, call `posthog:feature-flags-activity-retrieve` with `limit: 5, page: 1`. **Issue all calls in one message so they run concurrently** — sequential calls are dramatically slower.

```text
call feature-flags-activity-retrieve {"id": <flag_id>, "limit": 5, "page": 1}
```

Reasonable batch sizes:

- "last 7 days" → top 20–25 candidates
- "last 30 days" → top 50
- "last 90 days" → walk the full ~100

If you sample fewer than the full set, say so in the report and offer to walk the rest as a follow-up.

### 4. Extract the deletion event from each response

In each response, find the entry where `activity == "deleted"`. That entry's `created_at` is the actual deletion time, and `user.email` / `user.first_name` identify the deleter.

The deletion event's `detail.changes` array typically contains:

- `{field: "deleted", before: false, after: true}` — the actual delete
- `{field: "key", before: "<original>", after: "<original>:deleted:<id>"}` — Django renames the key on delete to free up the unique constraint
- `{field: "name", ...}` — the name sometimes gets reset

For most flags there's exactly one delete event. If a flag has been deleted-and-restored multiple times, take the most recent `activity: deleted` event within the window.

### 5. Filter and report

Filter the collected deletion events to those whose `created_at` falls inside the requested window. Present as a table:

| Flag ID | Key | Deleted at (UTC) | Deleted by |

State your methodology in the report (how many candidates you walked vs. how many soft-deleted flags exist total), so the user knows what was and wasn't checked.

## Watch-outs

- **Borderline cases**: if a deletion is within ~1 hour of the window cutoff, surface it as borderline rather than silently dropping it.
- **Don't trust `created_at` as a proxy for deletion time**: a flag created in 2024 can still have been deleted last week. The activity log is the only authority.
- **Renamed keys are normal**: a flag with key `foo:deleted:12345` was the flag originally keyed `foo`. The original key/name appears in the delete event's `detail.changes` array — surface that to the user, not the renamed form.
- **Walking all candidates is possible but slow**: ~100 parallel activity-log calls is doable. Offer it as a follow-up rather than the default for short windows.

## Example interaction

User: "what flags got deleted in the last week?"

1. Clarify if needed, or note both interpretations: "rolling 7 days ending now (UTC), in the active project"
2. Run the SQL enumeration to get up to 100 soft-deleted candidates ordered by `created_at DESC`
3. Fan out activity-log lookups in parallel across the top ~25 candidates
4. Extract `activity: deleted` entries; filter to those whose `created_at >= now - 7 days`
5. Report:

   ```text
   Found 2 feature flags deleted in the last 7 days (rolling, ending 2026-05-22 19:04 UTC):

   | Flag ID | Key                                       | Deleted at (UTC)     | Deleted by  |
   |---------|-------------------------------------------|----------------------|-------------|
   | 687432  | high_frequency_alerts                     | 2026-05-22 17:23     | Matt P.     |
   | 676665  | tasks-sendblue-prewarmed-sandbox-pool     | 2026-05-15 13:45     | Alessandro  |

   Methodology: walked the activity log for the 25 most-recently-created soft-deleted
   flags. Team 2 has ~100 soft-deleted flags total; the remaining ~75 were created
   before mid-March 2026 and were not checked. Want me to walk the rest?
   ```

## Related tools

- `posthog:execute-sql`: Used in step 2 to enumerate soft-deleted candidates against `system.feature_flags`
- `posthog:feature-flags-activity-retrieve`: Used in step 3 to find the actual deletion event for each candidate
- `posthog:feature-flag-get-definition`: Useful if the user then wants to inspect what the deleted flag looked like
