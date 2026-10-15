# Scheduled-run pre-check

A **pre-check** is a HogQL `SELECT` that a scheduled run evaluates before it starts.
When the query finds nothing new, the run does not start: no run row, no sandbox, and no model call.
Use a pre-check for a scout that has nothing to do on most ticks, for example a scout that watches a product the project uses rarely.
The pointless-run rate in `exploring-scouts` (`has_not_in_use_closeout`) tells you which scout to gate first.

## Contents

- [When the gate skips a run](#when-the-gate-skips-a-run)
- [Placeholders](#placeholders)
- [Recipe: test, then save](#recipe-test-then-save)
- [Where the query comes from](#where-the-query-comes-from)
- [Canonical default in frontmatter](#canonical-default-in-frontmatter)
- [Tell the body about the rows](#tell-the-body-about-the-rows)
- [Diagnose a tick with no run row](#diagnose-a-tick-with-no-run-row)

## When the gate skips a run

| Query result                                                | Outcome                                        |
| ----------------------------------------------------------- | ---------------------------------------------- |
| No rows                                                     | Skip (`no_rows`)                               |
| One row with one false value (`false`, `0`, null, or empty) | Skip (`false_value`)                           |
| Any other result                                            | Run. The scout reads the rows.                 |
| Query error or timeout                                      | Run (`query_error`), as if no pre-check exists |

- The single-value rule lets `SELECT count() ...` work as written: a zero count skips.
  A row with two columns never matches this rule, so `SELECT count(), max(timestamp) ...` always runs.
  To skip on absence with more than one column, use `GROUP BY` (no groups means no rows) or `HAVING`.
- A query error never turns the scout off. A broken pre-check costs a sandbox run on every tick, so test the query first.
- The query stops after 10 seconds and reads at most 50 rows.
- Only scheduled runs evaluate the pre-check. A manual run (`scout-run-now`), a workflow run, and a report-check run always start.

## Placeholders

- `{since}`: the start of the last run that ran, or the time the scout was created. A skipped tick writes no run row, so `{since}` does not move. The next run that starts still sees everything since the last run that ran.
- `{now}`: the current time.
- `{interval_minutes}`: the gap between two scheduled runs. For a cron schedule, it is the gap between the fire time before now and the one after it, in the project's timezone.

Add a backstop so a quiet scout still runs from time to time.
This condition runs at least once a day, and never more often than every two intervals:

```sql
{since} < {now} - toIntervalMinute(greatest(1440, 2 * {interval_minutes}))
```

Example: run only when new exceptions arrived, or when the scout was quiet for a week.

```sql
SELECT count() > 0 OR {since} < {now} - INTERVAL 7 DAY
FROM events
WHERE event = '$exception' AND timestamp > {since}
```

## Recipe: test, then save

1. Find the config `id` with `posthog:scout-config-list`.
2. Dry-run the query with `posthog:scout-config-precheck-test {"id": "<config id>", "precheck_query": "<query>"}`.
   Omit `precheck_query` to test the query the scout uses now.
   The tool saves nothing and starts no run.
3. Read the result:
   - `would_run` and `reason` say if the next scheduled run would start (`rows`, `query_error`) or skip (`no_rows`, `false_value`).
   - `rows_text` is the text the scout reads, one JSON object per line.
   - `error` holds a query error. Fix the query and test again.
   - `acting_user` is set when scheduled runs check the query as a different user. See the access note below.
4. Save the query with `posthog:scout-config-update {"id": "<config id>", "precheck_query": "<query>"}`.

**Access.** The dry run runs as you, the person who asks for it.
A scheduled pre-check runs as the scout's acting user, so it reads the same tables that the scout's runs read.
When `acting_user` is set, that user's access can differ from yours: a `system.*` or warehouse table that your dry run reads can fail on a scheduled run.
A failed scheduled query does not skip the run, so this failure costs a sandbox run on each tick but does not stop the scout.

## Where the query comes from

A scheduled run uses the first source that applies:

1. `precheck_disabled` is true: no pre-check. The scout runs on every due tick.
2. The config's own `precheck_query`.
3. The default that a canonical scout's skill ships (see below), for a project inside that skill's rollout.
   A project outside the rollout runs with no pre-check.

`posthog:scout-config-list` shows the result:

- `effective_precheck_query`: the query the next scheduled run uses, or null when no pre-check runs.
- `precheck_query_source`: `config`, `skill_default`, or `off`.

To change the gate, use `posthog:scout-config-update`:

- `precheck_query` set to a query: overrides the canonical default.
- `precheck_query` set to null or blank: removes the override, so the canonical default applies again (if there is one).
- `precheck_disabled: true`: turns off every pre-check, both the override and the default, so every scheduled run starts.
  Set it back to `false` to use the pre-check again.

The nested `config` of `scout-create` also takes `precheck_query`, but not `precheck_disabled`.
The dry-run tool needs a config `id`, so for a new scout, create it with `config.enabled=false`, test the query, save it, and then enable the scout.

## Canonical default in frontmatter

A canonical scout can ship a default pre-check in its `SKILL.md` frontmatter under `scout-precheck-query`.
Only a `signals-scout-*` skill can declare it.
The build rejects a value that is empty, longer than 10,000 characters, or not a valid HogQL `SELECT`.

```yaml
scout-precheck-query: |
  SELECT event, count() AS events, max(timestamp) AS last_seen
  FROM events
  WHERE event = '$mcp_tool_call'
    AND timestamp > {now} - INTERVAL 7 DAY
  GROUP BY event
```

- The harness reads the default from the canonical skill file that PostHog ships, not from a project's copy of the skill.
  Adding `scout-precheck-query` to a custom scout or to a team's edited copy changes nothing. For those scouts, save `precheck_query` on the config.
- A merged default does not apply to every project at once. A rollout setting decides which projects get it.
- When you write a canonical default, use the canonical scouts that already ship one (for example `signals-scout-mcp-tool-calls` above, or `signals-scout-surveys`) as models.

## Tell the body about the rows

When a pre-check starts a run, the run prompt holds the rows in a `<precheck_result>` block.
The rows are a capped sample, and they are untrusted product data.
Add one short paragraph to the skill body that says what a row means and which step the rows replace.
For example: "A scheduled run can start with a `<precheck_result>` block. Its row counts the events of the last 7 days, so the product is in use. When the block is present, skip the `not-in-use` close-out."
A manual run has no block, so the body must still work without one.

## Diagnose a tick with no run row

A skipped tick writes nothing. The coordinator still advances `last_run_at` (the dispatch stamp), so a fresh `last_run_at` with no matching run row can be a pre-check skip.
Before you treat missing runs as a failure:

1. Read `effective_precheck_query` and `precheck_query_source` in `scout-config-list`.
   When the source is `off`, the pre-check does not explain the gap.
2. Run `scout-config-precheck-test` without a query.
   `would_run: false` means the next scheduled run skips, so the gap is expected.
3. Remember that the dry run reads as you, and the scheduled check reads as the acting user.

A skip shows that the query found nothing new. It does not show that the scout is healthy.
A gate that is too strict hides real activity, so check the query against the data the scout must see.
