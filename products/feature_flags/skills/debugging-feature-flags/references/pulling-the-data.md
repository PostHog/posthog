# Pulling the data

Run this read-only before diagnosing or asking the customer anything. §1 and §2 produce the config and
the reproduced evaluation, and you need both on every ticket. §3 costs a scan of the project's events,
so reach for it only when §2 didn't settle the question or the ticket is about usage itself. Go
straight to §4 on "it used to work", and to §6 whenever the flag's `evaluation_runtime` isn't `all` —
that's the only step here that sees what a particular caller receives.

**Step 2 of the SKILL's workflow comes first.** Every call below answers for the session's **active**
project and takes no project ID, so if `posthog:switch-project` hasn't put you on the ticket's project
you get a complete, plausible answer about a different one — usually your own — with nothing to signal
it. Run the entitlement check, then come back here.

## 1. Flag config — `posthog:feature-flag-get-definition-by-key`

Pull these; the SKILL's reason expansions explain what each one causes, so this is a retrieval list,
not a second catalog.

- `key`, `active` — inactive returns false for everyone. See `disabled` / `flag_not_found`.
- `evaluation_runtime` — `all` (the default), `client`, or `server`. Anything but `all` can withhold
  the flag from a caller. See "Runtime scoping"; §6 checks it on the wire.
- `filters.groups[]` — the **release conditions**: `properties`, `rollout_percentage`, and `variant`
  (non-null forces that variant for the group rather than randomizing).
- `filters.multivariate.variants[]` — variant keys, percentages, and **stored order**.
- `filters.feature_enrollment`, plus the person property `$feature_enrollment/<key>` — early-access
  enrollment. See `super_condition_value`.
- `filters.aggregation_group_type_index` — flag-level only, and `null` on a **mixed** flag, so read
  each condition's own. See `no_group_type`.
- A `"type": "flag"` property inside `filters.groups[].properties` — a dependency on another flag.
  See `missing_dependency`.
- `ensure_experience_continuity` — pins a user's value across anonymous→identified, and makes §5
  unreliable.
- `payloads` — per-variant or boolean map; an empty or mismatched entry explains a blank payload.

Four carry gotchas the SKILL doesn't:

- `last_called_at` — batch-synced from `$feature_flag_called` on a schedule of tens of minutes rather
  than written per evaluation, so it lags live traffic and a stale-looking value proves nothing. It
  never advances at all when the SDK suppresses usage events. Don't quote it to a customer as evidence
  about whether their call arrived.
- `filters.holdout` — cross-check `posthog:experiment-holdouts-list`. A flag predating the holdout
  format change still carries a legacy `holdout_groups` array alongside it, so read `filters.holdout`
  and don't quote the stale percentage from `holdout_groups`.
- `bucketing_identifier` — `distinct_id` (the default) or `device_id`. §5 needs it, and `device_id` is
  incompatible with `ensure_experience_continuity`.
- `filters.super_groups` — legacy: dropped on write and not read by the matcher. Ignore it.

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

Map the returned reason with the reason table in [SKILL.md](../SKILL.md#known-cause-catalog--the-evaluation-reason-start-here),
and route from there.

**Neither tool reproduces the customer's runtime** (why, in the SKILL's `flag_not_found` expansion), so
on a flag scoped to `client` or `server` a clean match here does **not** clear runtime scoping. Only §6
does.

## 3. Historical usage — `posthog:execute-sql`

The `$feature_flag_called` event records what real clients actually got. Useful properties:
`$feature_flag` (the key), `$feature_flag_response` (the returned value/variant), `$feature_flag_reason`
(the match reason, same enum as above), `locally_evaluated`, `$used_bootstrap_value`,
`$feature_flag_request_id`, `$lib`, `$lib_version`.

Value + reason distribution over recent traffic. Keep `uniq` rather than `count(DISTINCT person_id)`,
which compiles to `uniqExact` and holds every person UUID in memory; if it still times out,
`uniq(distinct_id)` skips the person-overrides join too:

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

**The discriminator for runtime scoping** is a variant of the first query: drop the `$feature_flag`
predicate, filter on the caller's `$lib` instead, and group by flag key. Then read each returned key's
`evaluation_runtime`. If the flags that work are all `all` and the failing one isn't, the cause is
runtime scoping rather than targeting.

**Escape every value you substitute into a placeholder.** `<flag-key>`, `<lib>`, and `<distinct_id>` land
inside single-quoted SQL literals, and `posthog:execute-sql` takes no bound parameters — so a value
carrying a `'` closes the literal early and the rest is parsed as SQL. A `distinct_id` is whatever
the SDK sent, and it usually arrives via the ticket, so it is exactly the value you must not paste
raw: `x' OR 1=1 --` silently widens the predicate from one user to every user in the project, and
you then diagnose the customer's problem against someone else's history. HogQL escapes a quote as
`\'` and a backslash as `\\` inside a literal; apply both in a single pass over the value (never the
quote rule and then the backslash rule over your own output, which turns `x' OR 1=1 --` into the literal
`x\` followed by live SQL) before substituting.

If the flag records **no** `$feature_flag_called` at all despite being read, that's the "no usage"
catalog in the SKILL, not evidence the flag isn't evaluating.

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

**Treat a result as a hypothesis, never as evidence in a reply.** This is prose restating what
`rust/feature-flags/src/flags/flag_matching.rs` and `flag_matching_utils.rs` do, and no test binds the
two together — a change to a hash input, comparison, aggregation, or bucketing rule leaves this
returning a plausible wrong answer with nothing to flag it. Read those two files before you rely on it,
use the result only to decide where to look next, and quote a value to a customer only once §2 or a
`$feature_flag_called` event has confirmed it. PostHog's flag hash:

- **Rollout gate** (is the user in the rolled-out slice): `h = sha1(f"{flag_key}.{identifier}")`,
  take the first 15 hex digits and divide by `0xfffffffffffffff`; the user is **in** if
  `h <= rollout_percentage / 100`. Empty salt.
- **Variant walk** (which multivariate key): same hash but with the salt `"variant"`
  (`sha1(f"{flag_key}.{identifier}variant")`), then walk `filters.multivariate.variants` in stored
  order accumulating `rollout_percentage / 100`; the first bound **strictly** exceeding `h` wins.
  Mixing this salt with the rollout gate's empty one is the classic reimplementation bug, and a wrong
  stored order silently inverts the answer. Read both from the _live_ flag.
- **Holdout**: `h = sha1(f"holdout-{identifier}")`, same 15-hex-digit conversion. The flag key is
  **not** in this one — that's what makes a holdout consistent across every flag in it. Empty salt.
  The user is **in** the holdout if `h <= filters.holdout.exclusion_percentage / 100`.

For the rollout and variant hashes, `identifier` is resolved **per release condition**: the group key
when that condition is group-aggregated (its own `aggregation_group_type_index`, falling back to the
flag-level field when absent), otherwise the `distinct_id` — or the **device ID** under
`bucketing_identifier: "device_id"`. So a mixed flag hashes a group key for one condition and a
`distinct_id` for another. The **holdout** hash is the exception: it uses the **flag-level**
aggregation, so on a mixed flag the holdout hashes by `distinct_id`. SHA1 isn't in HogQL's whitelist,
so this runs outside the database.

## 6. What a caller actually receives (runtime scoping)

§2 reproduces the evaluation but not the **caller**, so on a flag scoped to `client` or `server` it
can't tell you whether the customer's app receives the flag at all. This does. Replay the flags request
against the customer's region three times, changing only the `User-Agent`, and compare whether the
flag's key is **present** in each response. Presence is the signal, not the value: the response keeps
the flags it evaluated to `false`, so an absent key means the flag never reached evaluation — which is
also what a server-side SDK surfaces as `false`.

**Keep the ticket's values out of the command text.** The `distinct_id` is whatever the SDK sent and
it reaches you through the ticket, so a `'` in it closes a quoted shell string and the rest runs as
commands. Single quotes don't save you, and neither does assigning first: `DID='<paste>'` and a
heredoc both still put the value in text a shell (or a Python parser) lexes. **Prefer a structured
HTTP client** — a request tool, or `urllib`/`requests` with the body passed as a `dict` — where the
value is an argument and there is no shell to escape for.

When `curl` is all you have, put the body in a **file** and let `curl` read it as data. Write that
file with your file-writing tool rather than a shell redirect, and let a JSON serializer escape the
value instead of quoting it by hand:

`/tmp/flags-body.json`

```json
{ "token": "<project_api_key>", "distinct_id": "<distinct_id>" }
```

The command then carries nothing from the ticket — `<region>` is `us` or `eu`, and the user agent is
one you pick:

```bash
URL='https://<region>.i.posthog.com/flags/?v=2'

# A — no verdict: `-A ''` sends no user agent, like an older SDK build, a hand-rolled
#     caller, or a header-stripping proxy.
curl -s -X POST "$URL" -A '' -H 'Content-Type: application/json' --data-binary @/tmp/flags-body.json
# B — client: posthog-js classifies as client-side (so does a browser Mozilla/… string).
curl -s -X POST "$URL" -H 'User-Agent: posthog-js/<version>' -H 'Content-Type: application/json' --data-binary @/tmp/flags-body.json
# C — server: posthog-node classifies as server-side.
curl -s -X POST "$URL" -H 'User-Agent: posthog-node/<version>' -H 'Content-Type: application/json' --data-binary @/tmp/flags-body.json
```

**Compare A against the arm matching the flag's own `evaluation_runtime`** — B for a `client` flag, C
for a `server` one. A request with no verdict is held to `all` flags, so a runtime-scoped flag is
missing from A whichever way it's scoped; only the matching arm shows it should have been there. Run
one arm and you get the trap: a `client`-scoped flag is absent from C as well, so a C-vs-A comparison
"clears" runtime scoping and sends you back to targeting. A flag present in its matching arm and
missing from A confirms runtime scoping.

**Set the header deliberately.** Bare `curl` sends `curl/<version>`, which is recognized as
server-side, so an unadorned request quietly reproduces arm C rather than arm A. `<project_api_key>` is
their public key, the one already in their client bundle. Older SDKs post to `/decide`, which runs the
same classification — but its response shape returns only enabled flags, so run this against `/flags`
where an evaluated `false` stays visible.

## Handing off

If a number or reason disproves a cause, drop it; if it confirms one, lead the reply with that
evidence. Convert every internal value to the customer's language before quoting it — see
[customer-reply.md](customer-reply.md).
