---
name: grouping-noisy-errors
description: >
  Consolidate PostHog error tracking issues that are the same actual
  error reported under different fingerprints. Use when the user asks
  "why do I have so many TypeError issues that look the same?", "merge
  these duplicates", "stop splitting this error into new issues", or
  wants to clean up fingerprint sprawl. Decides between a one-shot merge
  of existing issues and a durable grouping rule that keeps future
  events from creating new fingerprints. Does NOT group conceptually
  similar bugs across different runtimes, SDKs, or call sites.
---

# Grouping noisy errors

The same error can be reported as dozens of separate issues when stack frames or
messages contain volatile data — random IDs, dynamic file paths, build hashes,
anonymous function names. The fix is two-step: merge the existing issues into one
target, then create a grouping rule so future events from the same call site
share a single canonical fingerprint instead of spawning new ones.

Important up front: "same error" here is narrow. Two issues that share a name or
a sentence of message text but came from different code paths, different SDKs,
or different runtimes are **different errors** and should stay separate, even if
the user thinks of them as "the same kind of bug". Grouping a frontend
`TypeError` together with a backend `TypeError` because both messages contain
"undefined" destroys the signal that lets the team find each one. The criteria
in step 1 exist to keep that from happening.

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
| `posthog:error-tracking-issues-partial-update` | Rename or re-describe the target after a merge         |

## Merge vs grouping rule

The two tools solve different halves of the problem:

- **Merge** is one-shot. It collapses existing issues into a target and re-attaches
  their events. Future events still group by their original fingerprints — if the
  same noisy pattern keeps producing new fingerprints, merging is a treadmill.
- **Grouping rule** is durable. It rewrites the fingerprint of any matching
  event to `custom-rule:<rule_id>` at ingestion time, so all future matches
  share one canonical fingerprint rather than spawning new ones. The first
  match either creates a new issue keyed off that fingerprint, or routes to
  whatever issue is already bound to it.

Use both together when the issue is recurring: merge historical duplicates
into a target issue, then create the rule. The rule API does **not** accept a
target issue ID — once the rule starts firing, the resulting `custom-rule:...`
issue can be merged into the same target so the consolidation sticks. Use
merge alone for historical sprawl that you don't expect to recur. Use a
grouping rule alone for a brand-new pattern you're getting ahead of, when
you don't need to consolidate with an existing issue.

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
same top frame and same exception type, they're likely the same error — but
verify against the full checklist below before merging.

#### Are they the same error?

Treat two issues as duplicates only when **every one** of these matches:

- `$lib` is the same SDK (`posthog-js`, `posthog-python`, `posthog-node`,
  `posthog-android`, etc.). Errors from different SDKs almost always come from
  different code paths even when the exception type matches.
- The exception type is identical (`$exception_types`).
- The top in-app stack frame points at the same file and same function. Line
  numbers and minor offsets within that function are fine; a different file or
  a different function on top means a different bug.
- The message follows the same template, with differences confined to volatile
  data — IDs, hashes, timestamps, dynamic paths. If the difference is a
  different verb, object, or operation, it's a different bug.
- `$exception_handled` agrees (both handled or both unhandled). A caught
  variant and an uncaught variant are different code paths and benefit from
  staying separate.

If any single one of those differs, they are not duplicates — investigate
separately (`investigating-error-issue`).

#### What NOT to group together

These are the failure modes that destroy debugging signal. Do not group
across any of them, even when the user describes them as "the same kind of
bug":

- **Frontend and backend variants of the same exception type.** A `TypeError`
  from a browser bundle and a `TypeError` from a Node service share a name and
  often a message word, but the stack, the runtime, and the fix all differ.
- **Different SDKs / platforms.** `posthog-js` vs `posthog-python` vs
  `posthog-android` are different call sites.
- **Same type, different file or function on top of the stack.** A
  `NullPointerException` thrown from `OrderService.cancel` is not the same bug
  as one thrown from `PaymentService.refund`, even if both messages say
  "user was null".
- **Caught vs uncaught.** Two issues that differ only in `$exception_handled`
  are usually a code path that swallows the error in one place and lets it
  propagate in another — keeping them separate makes that visible.
- **Conceptually-similar bugs that happen to share a phrase.** "Cannot read
  property of undefined" appears in many independent bugs. Without matching
  stack frames, message similarity alone is not enough.

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

Merged changes may not appear in the issue list immediately — re-listing right
after the call can still show the source issues for a short window. If a
follow-up `error-tracking-issues-list` call looks unchanged, wait a few seconds
and re-query rather than re-issuing the merge.

If after the merge the target's metadata looks wrong (a duplicate had a better
name), use `error-tracking-issues-partial-update` to fix the name or description
on the target rather than re-merging.

### Step 4 — Decide if a grouping rule is warranted

A grouping rule is worth creating when both are true:

- The pattern keeps producing new fingerprints (you have seen new duplicates
  appear since the last merge)
- You can describe the pattern with property filters that won't accidentally
  swallow unrelated errors

The canonical exception properties (`$exception_types`, `$exception_values`
for messages, `$exception_sources` for file paths, `$exception_functions` for
function names) are arrays at capture time. The property filter compiler
[special-cases them](https://github.com/PostHog/posthog/blob/master/posthog/hogql/property.py#L904) — it parses the JSON-materialized column
and wraps the filter in `arrayExists(v -> ..., JSONExtract(...))`, so all
the standard operators (`exact`, `is_not`, `icontains`, `not_icontains`,
`regex`, `not_regex`) work against individual elements with the bare value:
`exact "TypeError"`, not `exact '["TypeError"]'` or `regex '"TypeError"'`.

The singular forms (`$exception_type`, `$exception_message`) and
`$exception_stack_trace_raw` are emitted on a fraction of a percent of events;
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

Translate the step 1 "same error" checklist into rule filters. A rule that
matches more loosely than the checklist will silently merge unrelated bugs
forever — the rule is more dangerous than the merge because it runs against
every future event. At a minimum, scope by SDK and exception type, and add
a third dimension (file path via `$exception_sources`, or a specific message
phrase via `$exception_values`) to pin the call site:

```json
posthog:error-tracking-grouping-rules-create
{
  "filters": {
    "type": "AND",
    "values": [
      {
        "type": "event",
        "key": "$lib",
        "operator": "exact",
        "value": "posthog-js"
      },
      {
        "type": "event",
        "key": "$exception_types",
        "operator": "exact",
        "value": "TypeError"
      },
      {
        "type": "event",
        "key": "$exception_sources",
        "operator": "icontains",
        "value": "/static/checkout/"
      },
      {
        "type": "event",
        "key": "$exception_values",
        "operator": "icontains",
        "value": "Cannot read property"
      }
    ]
  },
  "description": "Cleanup: collapse noisy checkout TypeError fingerprints (posthog-js)"
}
```

Rules are evaluated in order. List existing rules first
(`posthog:error-tracking-grouping-rules-list`) — if a rule already partially
covers the pattern, prefer adjusting its filter over stacking a near-duplicate.

The optional `assignee` field auto-assigns issues created by the rule. Skip it
unless the user explicitly wants ownership baked into the rule.

### Step 6 — Verify and consolidate

Sample the merged issue's recent events to confirm the merge succeeded.
Watch for the rule's `custom-rule:<rule_id>` fingerprint to start matching
events — the first match creates a new issue (or routes to whatever was
already bound to that fingerprint). To keep events under your historical
target rather than scattered across the new custom-rule issue, run a second
merge folding the custom-rule issue into the target.

If new (non-rule) fingerprints continue appearing despite the rule, its
filter is too narrow — widen it.

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
