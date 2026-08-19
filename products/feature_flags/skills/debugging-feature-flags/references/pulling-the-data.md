# Pulling the data

Run this read-only before diagnosing or asking the customer anything. §1 and §2 produce the config and
the reproduced evaluation, and you need both on every ticket. §3 costs a scan of the project's events,
so reach for it only when §2 didn't settle the question, or when the ticket is about usage itself — "I
see no `$feature_flag_called`", "works locally but not in production", or "the value flipped".

**Step 2 of the SKILL's workflow comes first.** Every call below answers for the session's **active**
project and takes no project ID, so if `posthog:switch-project` hasn't put you on the ticket's project
you get a complete, plausible answer about a different one — usually your own — with nothing to signal
it. Run the entitlement check, then come back here.

## 1. Flag config — `posthog:feature-flag-get-definition-by-key`

Pull these fields; they are inputs to almost every cause:

- `key`, `active` — a `false` here means the flag is inactive: it returns false for everyone.
  `evaluation-reasons` names that state `disabled`, and `test-evaluation` names it `flag_not_found` —
  but `flag_not_found` covers more than inactive, so read `evaluation_runtime` too before concluding
  anything from it (see the SKILL's `disabled` / `flag_not_found` expansion).
- `evaluation_runtime` — `all` (the default), `client` (client-side SDKs only), or `server` (server-side
  SDKs only). PostHog omits the flag from the `/flags` response for callers on the other side, so a
  mismatch against the ticket's `$lib` explains an `undefined` the release conditions don't. It's also
  why `test-evaluation` can return `flag_not_found` for an active flag.
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
  `holdout_condition_value`. Cross-check `posthog:experiment-holdouts-list`. (A flag created before the
  holdout format change still carries a legacy `holdout_groups` array alongside it — the backfill added
  the new key without removing the old one, so read `filters.holdout` and don't quote the stale
  percentage from `holdout_groups`.)
- `filters.aggregation_group_type_index` — the **flag-level** aggregation, and only a summary:
  aggregation is set **per release condition**, so each entry in `filters.groups[]` carries its own
  `aggregation_group_type_index`. This flag-level field is `null` when the conditions are **mixed**
  (some group-aggregated, some person-aggregated) even though group conditions exist, so read the
  per-condition field on each group, not just this one. A group condition evaluated without its
  `groups` passed is skipped (`no_group_type`) while the **other** conditions still evaluate — a
  mixed flag doesn't wholesale return false, so a person condition can still decide the value.
- Flag dependencies — a property of type `flag` in `filters.groups[].properties` means this flag
  gates on another flag and fails **closed** (`missing_dependency`) when the parent is absent (deleted
  or part of a cycle). The `"type": "flag"` entry holds the parent's numeric ID — pass it to
  `posthog:feature-flag-get-definition`. (`posthog:feature-flags-dependent-flags-retrieve` goes the other way: it lists
  flags that depend on _this_ one.)
- `ensure_experience_continuity` — if `true`, assignment hashes a stored override key so a user's
  value is pinned across anonymous→identified transitions (and the offline hash check below is
  unreliable).
- `bucketing_identifier` — `distinct_id` (the default) or `device_id`. It decides which identifier the
  rollout and variant hashes consume, so §5 needs it; `device_id` is incompatible with
  `ensure_experience_continuity`.
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

Value + reason distribution over recent traffic. `uniq` is an approximate counter (~0.5% error), which
is all a "roughly how many users got each value" diagnostic needs — `count(DISTINCT person_id)` compiles
to `uniqExact` and holds every distinct person UUID in memory for the query's duration. If it still times
out, `uniq(distinct_id)` reads a column physically on `events` and skips the person-overrides join that
`person_id` resolves through:

```sql
SELECT
  properties.$feature_flag_response AS value,
  properties.$feature_flag_reason AS reason,
  coalesce(properties.$lib, '(none)') AS lib,
  countIf(toString(properties.locally_evaluated) = 'true') AS locally_evaluated,
  count() AS calls,
  uniq(person_id) AS persons
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

**Escape every value you substitute into a placeholder.** `<flag-key>` and `<distinct_id>` land
inside single-quoted SQL literals, and `posthog:execute-sql` takes no bound parameters — so a value
carrying a `'` closes the literal early and the rest is parsed as SQL. A `distinct_id` is whatever
the SDK sent, and it usually arrives via the ticket, so it is exactly the value you must not paste
raw: `x' OR 1=1 --` silently widens the predicate from one user to every user in the project, and
you then diagnose the customer's problem against someone else's history. HogQL escapes a quote as
`\'` and a backslash as `\\` inside a literal; apply both in a single pass over the value (never the
quote rule and then the backslash rule over your own output, which turns `x' OR 1=1 --` into the literal
`x\` followed by live SQL) before substituting.

If the flag records **no** `$feature_flag_called` at all despite being read, that's the "no usage"
catalog in the SKILL (events disabled, bulk/payload accessor, or local eval without per-call events)
— not evidence the flag isn't evaluating.

## 4. Change history — `posthog:feature-flags-activity-retrieve`

`posthog:feature-flags-activity-retrieve { id: <flag_id> }` gives field-level diffs (who changed the
conditions/rollout/variants, and when). Most "it changed / it used to work" surprises are a condition
or rollout edit visible here. It returns only the **10 newest** rows by default (newest-first), so on a
flag edited more than a handful of times the change you're after can sit off the first page — raise
`limit` or walk `page` until the results pass the time you care about, using the `next` URL and
`total_count` in the response as the signal there's more. Don't read an empty first page as "nothing
changed".

`posthog:advanced-activity-logs-list` covers the same rows across the project, carrying `item_id` (the
flag's numeric ID) and `detail.name` (its key) — sweep with `scopes: ["FeatureFlag"]` plus `search_text`
or `detail_filters` when the customer can't name the flag, then come back here for the field-level diff.

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
- **Holdout**: `h = sha1(f"holdout-{identifier}")`, same 15-hex-digit conversion. The flag key is
  **not** in this one — that's what makes a holdout consistent across every flag in it. Empty salt.
  The user is **in** the holdout if `h <= filters.holdout.exclusion_percentage / 100`.

For the rollout and variant hashes, `identifier` is resolved **per release condition**: the group key
when that condition is group-aggregated (read its own `aggregation_group_type_index` in
`filters.groups[]`, which falls back to the flag-level field when absent), otherwise the `distinct_id`
— or the **device ID** when the flag sets `bucketing_identifier: "device_id"`. A **mixed** flag hashes a
group key for one condition and a `distinct_id` for another, so don't read only the flag-level
`aggregation_group_type_index` (it's `null` on a mixed flag) — read each condition's, with the rest of
the config in §1. The **holdout** hash is the exception: it uses the **flag-level** aggregation, so on a
mixed flag the holdout hashes by `distinct_id`. SHA1 isn't in HogQL's whitelist, so this runs outside the
database. `ensure_experience_continuity = true` makes it unreliable (assignment hashes a stored override
key).

## Handing off

If a number or reason disproves a cause, drop it; if it confirms one, lead the reply with that
evidence. Convert every internal value to the customer's language before quoting it — see
[customer-reply.md](customer-reply.md).
