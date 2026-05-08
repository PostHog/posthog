---
name: grouping-noisy-errors
description: >
  Consolidate PostHog error tracking issues that share the same root
  cause but were split into many separate fingerprints. Use when the
  user asks "why do I have so many TypeError issues that look the same?",
  "merge these duplicates", "stop splitting this error into new issues",
  or wants to clean up fingerprint sprawl. Decides between a one-shot
  merge of existing issues and a durable grouping rule that keeps future
  events from creating new fingerprints.
---

# Grouping noisy errors

A single root cause can show up as dozens of separate issues when stack frames or
messages contain volatile data — random IDs, dynamic file paths, build hashes,
anonymous function names. The fix is two-step: merge the existing issues into one
target, then create a grouping rule so future events with the same cause attach to
that issue instead of spawning new fingerprints.

## Available tools

| Tool                                           | Purpose                                                |
| ---------------------------------------------- | ------------------------------------------------------ |
| `posthog:query-error-tracking-issues-list`     | Find candidate duplicate issues                        |
| `posthog:query-error-tracking-issue`           | Pull compact details for an individual issue           |
| `posthog:query-error-tracking-issue-events`    | Sampled `$exception` events with stack and message     |
| `posthog:error-tracking-issues-merge-create`   | Merge existing issues into a target                    |
| `posthog:error-tracking-issues-split-create`   | Surgically split fingerprints back out if a merge errs |
| `posthog:error-tracking-grouping-rules-create` | Auto-group future events into one issue                |
| `posthog:error-tracking-grouping-rules-list`   | Check existing grouping rules before adding new ones   |

## Merge vs grouping rule

The two tools solve different halves of the problem:

- **Merge** is one-shot. It collapses existing issues into a target and re-attaches
  their events. Future events still group by their original fingerprints — if the
  same noisy pattern keeps producing new fingerprints, merging is a treadmill.
- **Grouping rule** is durable. It defines a filter that pulls matching exception
  events into a designated issue at ingestion time. New events with the same
  pattern attach to that issue rather than spawning new fingerprints.

Use both together when the issue is recurring: merge what already exists, then
create a grouping rule so the cleanup sticks. Use merge alone for historical
sprawl that you don't expect to recur. Use a grouping rule alone for a
brand-new pattern you're getting ahead of.

## Workflow

### Step 1 — Confirm the duplicates

Search by exception type or message to find candidates:

```json
posthog:query-error-tracking-issues-list
{
  "searchQuery": "TypeError: Cannot read property",
  "status": "active",
  "limit": 50,
  "orderBy": "occurrences",
  "dateRange": { "date_from": "-30d" }
}
```

For each candidate, pull one sampled exception event to compare stack, type,
and message:

```json
posthog:query-error-tracking-issue-events
{
  "issueId": "<candidate_issue_id>",
  "limit": 1,
  "verbosity": "stack"
}
```

Run this once per candidate. The tool defaults to `onlyAppFrames: true`, which
makes the top in-app frame stand out at a glance. If two candidates share the
same top frame and same exception type, they're almost certainly the same bug.

They share a root cause if all three are true:

- The exception type is identical
- The message follows the same pattern (only volatile parts differ — IDs, hashes,
  paths)
- The top stack frames point at the same file and function (line numbers can
  differ slightly)

If any of those differ, they are not duplicates — investigate separately
(`investigating-error-issue`).

### Step 2 — Pick the target issue

Pick the issue that should absorb the others:

- **Most occurrences** — keeps the dominant issue so dashboards stay continuous
- **Best name and description** — if the user has annotated one, prefer it
- **Earliest `first_seen`** — preserves the original timeline

Note the target's ID. The other candidates become `ids` to merge in.

### Step 3 — Merge existing duplicates

```json
posthog:error-tracking-issues-merge-create
{
  "id": "<target_issue_id>",
  "ids": ["<duplicate_id_1>", "<duplicate_id_2>", "..."]
}
```

Merge is destructive (annotation `destructive: true`) — once issues are merged
into a target, the source issues are gone from the active list. Confirm the
target with the user before calling. Cap each merge call at ~50 source IDs to
keep failures localized; for larger sprawl, batch.

If after the merge the target's metadata looks wrong (a duplicate had a better
name), use `error-tracking-issues-partial-update` to fix the name or description
on the target rather than re-merging.

### Step 4 — Decide if a grouping rule is warranted

A grouping rule is worth creating when both are true:

- The pattern keeps producing new fingerprints (you have seen new duplicates
  appear since the last merge)
- You can describe the pattern with property filters that won't accidentally
  swallow unrelated errors

The canonical exception properties are plural arrays — `$exception_types`,
`$exception_values` (messages), `$exception_sources` (file paths),
`$exception_functions` (function names). Filter engines handle array
containment, so a scalar `value` with `exact`/`icontains`/`regex` matches if
any element does. Singular forms (`$exception_type`, `$exception_message`) and
`$exception_stack_trace_raw` are not emitted by the modern ingestion path —
filtering on them produces a rule that silently never matches.

If the volatility is in the message (e.g.,
`TypeError at /static/main.<hash>.js`), a regex filter on `$exception_values`
works. If the volatility is in line numbers within a known file, `icontains`
on `$exception_sources` does. `$exception_handled` is also a useful narrowing
dimension — separate handled vs unhandled rather than mixing them.

Skip the grouping rule when:

- The duplicates are historical (one-off backfill, no new occurrences) — merge
  is enough
- You can't write a filter narrow enough to be safe — broaden the merge cadence
  instead and revisit later

### Step 5 — Create the grouping rule

```json
posthog:error-tracking-grouping-rules-create
{
  "filters": {
    "type": "AND",
    "values": [
      {
        "type": "event",
        "key": "$exception_types",
        "operator": "exact",
        "value": "TypeError"
      },
      {
        "type": "event",
        "key": "$exception_values",
        "operator": "icontains",
        "value": "Cannot read property"
      }
    ]
  },
  "description": "Cleanup: collapse noisy TypeError fingerprints from main bundle"
}
```

Rules are evaluated in order. List existing rules first
(`posthog:error-tracking-grouping-rules-list`) — if a rule already partially
covers the pattern, prefer adjusting its filter over stacking a near-duplicate.

The optional `assignee` field auto-assigns issues created by the rule. Skip it
unless the user explicitly wants ownership baked into the rule.

### Step 6 — Verify

Sample the merged issue's recent events to confirm the merge succeeded and
watch for new fingerprints over the next 24h. If new duplicates still appear,
the grouping rule's filter is too narrow — widen it.

## Tips

- The user often confuses grouping rules with assignment rules. Grouping rules
  decide _which_ issue an event lands in. Assignment rules decide _who_ owns the
  resulting issue.
- Don't merge issues that "look similar" without inspecting events. Two
  `TypeError`s in different files are different bugs.
- Stack frames are the canonical grouping signal — ingestion already
  fingerprints on the stack, so a stable stack groups itself. A grouping rule
  is for cases where the natural fingerprint sprays (volatile filenames,
  hashed function names, dynamic line numbers) and you need to override it.
- Disabling or tightening a grouping rule does not retroactively un-group
  existing events; future events route correctly, past events stay where they
  are. Use `error-tracking-issues-split-create` if you need to surgically
  separate fingerprints back out of a merged issue.
- Grouping rules are visible in the UI under Project settings → Error tracking →
  Grouping rules; mention this when the user asks where rules live.
