# Pulling the data

Run this read-only before diagnosing or asking the customer anything. It produces the config, the
reproduced evaluation, and the usage numbers you'll cite back to them.

## 1. Flag config — `posthog:feature-flag-get-definition-by-key`

Pull these fields; they are inputs to almost every cause:

- `key`, `active` — a `false` here means the flag is inactive: it returns false for everyone, and the
  reproduction tools name that state `disabled` / `flag_not_found` (see the SKILL's `disabled`
  expansion for why they differ).
- `filters.groups[]` — the **release conditions**. Per group read `properties` (the targeting),
  `rollout_percentage`, and `variant` (a non-null variant is a forced assignment for that group, not
  randomized).
- `filters.multivariate.variants[]` — variant keys, percentages, and **stored order** (the variant
  hash walks them in this order).
- `filters.feature_enrollment` (plus the person property `$feature_enrollment/<key>`) — **early-access
  enrollment**: an early-return override evaluated _before_ the release conditions (reason
  `super_condition_value`); see the SKILL's `super_condition_value` expansion. (`filters.super_groups`
  is a legacy key: dropped on write and not read by the matcher.)
- `filters.holdout` — a global holdout; matched users return the holdout value, reason
  `holdout_condition_value`. Cross-check `posthog:experiment-holdouts-list`.
- `filters.aggregation_group_type_index` — if set, the flag is **group-aggregated**: every SDK
  evaluation must pass the matching `groups`, or it returns false (`no_group_type`).
- Flag dependencies — a property of type `flag` in `filters.groups[].properties` means this flag
  gates on another flag and fails **closed** (`missing_dependency`) when the parent is absent (deleted
  or part of a cycle). The `"type": "flag"` entry holds the parent's numeric ID — pass it to
  `posthog:feature-flag-get-definition`. (`posthog:feature-flags-dependent-flags-retrieve` goes the other way: it lists
  flags that depend on _this_ one.)
- `ensure_experience_continuity` — if `true`, assignment hashes a stored override key so a user's
  value is pinned across anonymous→identified transitions (and the offline hash check below is
  unreliable).
- `payloads` — per-variant (or boolean) payload map; an empty/mismatched entry explains a blank
  payload.

## 2. Reproduce the evaluation (the decisive step)

PostHog evaluates the flag for you server-side and returns the **match reason** — no guessing:

- **`posthog:feature-flags-evaluation-reasons-retrieve`** — give a `distinct_id`, and **scope it with
  `flag_keys`** to the flag(s) you're debugging (omitting it returns an entry for every flag in the
  project). Pass `groups` (a JSON object string) for a group-aggregated flag. Returns the evaluated
  value and reason for that user. Start here.
- **`posthog:feature-flags-test-evaluation-create`** — single flag for a specific user, with detailed
  reasoning, at an optional point in time. Use for a deep dive or to check a historical moment.
- **`posthog:feature-flags-status-retrieve`** — health/staleness (active / stale / deleted / unknown).
- **`posthog:feature-flags-user-blast-radius-create`** — how many users a release condition would match;
  run this **before** recommending the customer widen a condition.

Map the returned reason with the reason table in [SKILL.md](../SKILL.md#known-cause-catalog--the-evaluation-reason-start-here).
If the reproduced value **matches** what the customer expected but they still report the wrong value,
the cause is client-side — go to the SDK catalog in the SKILL.

## 3. Historical usage — `posthog:execute-sql`

The `$feature_flag_called` event records what real clients actually got. Useful properties:
`$feature_flag` (the key), `$feature_flag_response` (the returned value/variant), `$feature_flag_reason`
(the match reason, same enum as above), `locally_evaluated`, `$used_bootstrap_value`,
`$feature_flag_request_id`, `$lib`, `$lib_version`.

Value + reason distribution over recent traffic:

```sql
SELECT
  properties.$feature_flag_response AS value,
  properties.$feature_flag_reason AS reason,
  coalesce(properties.$lib, '(none)') AS lib,
  countIf(toString(properties.locally_evaluated) = 'true') AS locally_evaluated,
  count() AS calls,
  count(DISTINCT person_id) AS persons
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag = '<flag-key>'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY value, reason, lib
ORDER BY calls DESC
LIMIT 50
```

One user's history (what that `distinct_id` actually received, and whether it flipped):

```sql
SELECT
  timestamp,
  properties.$feature_flag_response AS value,
  properties.$feature_flag_reason AS reason,
  properties.locally_evaluated AS locally_evaluated,
  properties.$used_bootstrap_value AS bootstrapped,
  properties.$lib AS lib
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag = '<flag-key>'
  AND distinct_id = '<distinct_id>'
  AND timestamp >= now() - INTERVAL 30 DAY
ORDER BY timestamp DESC
LIMIT 100
```

If the flag records **no** `$feature_flag_called` at all despite being read, that's the "no usage"
catalog in the SKILL (events disabled, bulk/payload accessor, or local eval without per-call events)
— not evidence the flag isn't evaluating.

## 4. Change history — `posthog:feature-flags-activity-retrieve`

`posthog:feature-flags-activity-retrieve { id: <flag_id> }` gives field-level diffs (who changed the
conditions/rollout/variants, and when). Most "it changed / it used to work" surprises are a condition
or rollout edit visible here. Note the `posthog:advanced-activity-logs-list` "feature flag updated" row does
**not** carry the flag key — use the per-flag activity endpoint when you need to prove _which_ flag
changed.

## 5. Offline rollout / variant hash (fallback only)

You rarely need this — §2 reproduces evaluation authoritatively. Reach for it only when you can't
reach the instance (e.g. a cross-region block) and must recompute from an exported `distinct_id`.
PostHog's flag hash, verified against `rust/feature-flags/src/flags/flag_matching.rs` and
`flag_matching_utils.rs`:

- **Rollout gate** (is the user in the rolled-out slice): `h = sha1(f"{flag_key}.{identifier}")`,
  take the first 15 hex digits and divide by `0xfffffffffffffff`; the user is **in** if
  `h <= rollout_percentage / 100`. Empty salt.
- **Variant walk** (which multivariate key): same hash but with the salt `"variant"`
  (`sha1(f"{flag_key}.{identifier}variant")`), then walk `filters.multivariate.variants` in stored
  order accumulating `rollout_percentage / 100`; the first bound **strictly** exceeding `h` wins.
  Two things to get right: the salt (the rollout gate above uses an _empty_ one, and mixing the two
  is the classic reimplementation bug), and the stored order, since a wrong order silently inverts
  the answer. Read both from the _live_ flag.
- **Holdout**: prefix `holdout-` with an empty salt.

`identifier` is the `distinct_id`, or the group key for a group-aggregated flag. SHA1 isn't in
HogQL's whitelist, so this runs outside the database. `ensure_experience_continuity = true` makes it
unreliable (assignment hashes a stored override key).

## Handing off

If a number or reason disproves a cause, drop it; if it confirms one, lead the reply with that
evidence. Convert every internal value to the customer's language before quoting it — see
[customer-reply.md](customer-reply.md).
