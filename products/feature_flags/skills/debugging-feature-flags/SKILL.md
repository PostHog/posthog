---
name: debugging-feature-flags
description: >-
  Debug and support PostHog Feature Flags for a customer whose flag isn't
  behaving. Use whenever a flag support ticket is pasted or a customer asks a
  flag-evaluation question — most commonly "my flag isn't showing / returns
  false for a user who should get it", "the flag is on for everyone", "it
  returns undefined / the wrong variant", "the payload is empty", "it works
  locally but not in production", or "the flag works but I see no usage". Pulls
  the flag's config and reproduces the evaluation read-only (server-side match
  reason first), matches it to a known-cause catalog, and produces a
  customer-facing explanation, fix, and the evidence.
  TRIGGER when: a customer/ticket asks why a flag returns the wrong value for a
  user, why a variant/payload is wrong, why a flag is on for everyone or no one,
  why it differs between local and production, or why a flag records no usage —
  and you need to explain it back to them.
  DO NOT TRIGGER when: the flag backs an experiment and the question is about
  experiment results (use debugging-experiments), cleaning up stale flags (use
  cleaning-up-stale-feature-flags), copying flags across projects (use
  copying-flags-across-projects), or a broad hygiene audit (use
  auditing-experiments-flags).
---

# Debugging feature flags

A PostHog feature flag evaluates to a value for a given user: `true`/`false` for a boolean flag,
or a **variant** key for a multivariate flag, optionally with a **payload**. The value is decided by
the flag's **release conditions** (property targeting + a rollout percentage), evaluated either
server-side (via PostHog's `/flags` endpoint) or by the SDK locally. When the SDK reads the flag it
can also record a `$feature_flag_called` **usage** event. A customer looks at a value they didn't
expect and asks why.

**Most flag tickets are targeting, evaluation-context, or SDK-integration problems, not evaluation
bugs.** The hashing is deterministic and the rules are what they are; usually the user's properties
don't match, the eval context (`distinct_id` / groups) is wrong, or the SDK is reading a stale or
not-yet-loaded value. The job is to find **which**, prove it with the flag's own evaluation, and hand
back a plain-language explanation plus the fix.

The big lever versus other debugging: **PostHog can reproduce the evaluation for you server-side.**
`feature-flags-evaluation-reasons-retrieve` and `feature-flags-test-evaluation-create` return the
value _and_ the **match reason** for a specific user — so you rarely have to guess. Lead with that.

## Debugging workflow

1. **Parse the ticket.** Extract project ID, instance (US vs EU — URLs and data live in different
   places), the flag **key**, the affected **`distinct_id`** and any **groups**, the SDK/`$lib` and
   version, the **expected vs actual** value, and whether it's local vs production. Aged tickets are
   dirty — re-pull current config and treat earlier claims as stale.
2. **Resolve the flag.** `feature-flag-get-definition-by-key` (or `feature-flag-get-all` to search),
   and pull the config fields in [references/pulling-the-data.md](references/pulling-the-data.md).
3. **Reproduce the evaluation server-side.** This is the step that usually answers it. Run
   `feature-flags-evaluation-reasons-retrieve` with the affected `distinct_id`, scoped with
   `flag_keys` to the flag you're debugging (omitting it returns every flag — a huge payload), plus
   `groups` for a group-aggregated flag. It returns the flag's value and the **match reason**. For a
   point-in-time or single-flag deep dive use `feature-flags-test-evaluation-create` (by numeric flag
   `id`, with an optional `timestamp`), which also returns per-condition detail. Map the reason to
   the catalog below. Verify from data before asking the customer anything.
4. **Decide server-truth vs client-report.** If the server reason **explains** the reported value,
   it's a config/targeting/context cause (reason catalog below). If the server says the flag
   **matches** but the customer still doesn't get it, the problem is **client-side** — jump to the
   SDK catalog.
5. **Scope the fix to the flag's state.** A flag mutation (widening a condition, raising rollout,
   enabling) is a live change to real traffic — say so, estimate the blast radius with
   `feature-flags-user-blast-radius-create` when widening, and never mutate a customer's flag without
   explicit consent. Prefer precise guidance over editing their flag for them.
6. **Write the reply** using [references/customer-reply.md](references/customer-reply.md): cause →
   fix → the evaluation/reason that proves it, in the customer's UI language.

## Known-cause catalog — the evaluation reason (start here)

`feature-flags-evaluation-reasons-retrieve` / `-test-evaluation-create` return a **match reason**
(also recorded on each `$feature_flag_called` event as `$feature_flag_reason`). Map it:

| Reason                                                        | What it means                                                                                          | Likely cause & fix                                                                                                                                                                                                   |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `condition_match`                                             | A release condition matched and the user is inside its rollout                                         | Working as configured. If "on for everyone" is unwanted, the matched condition is too broad or its rollout is 100% — tighten the condition/rollout.                                                                  |
| `no_condition_match`                                          | No release condition matched                                                                           | Usually the user's properties don't satisfy any condition — a missing property, a value/type/case mismatch, or `$initial_` vs current property. Confirm the exact property on the person; fix the condition or the property. **On a flag with group conditions this can instead be a skipped group** — see the `no_group_type` row and the expansion below. |
| `out_of_rollout_bound`                                        | Conditions matched, but the user hashed **above** the rollout %                                        | Deterministic: the user isn't in the rolled-out slice. Raising the rollout % includes more users; the same user only flips in once the % passes their hash point.                                                    |
| `no_group_type` / `no_condition_match` (groups not evaluated) | The flag is **group-aggregated** but the SDK call didn't pass the group (or the group type is unknown) | The `getFeatureFlag` call must pass `groups: { <type>: <key> }`. Without it, group conditions are skipped and the flag returns false.                                                                                |
| `super_condition_value`                                       | An **early-access enrollment override** (early-return) decided the value                               | Early-access feature enrollment short-circuits normal targeting. It's driven by `filters.feature_enrollment` plus the person property `$feature_enrollment/<flag_key>` — check both; that's why the value ignores the release conditions. (`filters.super_groups` is the legacy encoding; the matcher no longer evaluates it.) |
| `holdout_condition_value`                                     | The user is in a **global holdout**                                                                    | The flag returns the holdout value by design. Expected if a holdout is attached; check `filters.holdout` / `experiment-holdouts-list`.                                                                               |
| `disabled` (`evaluation-reasons`) / `flag_not_found` (`test-evaluation`) | The flag isn't active                                                                        | Enable the flag (`active: true`). Until then it returns false for everyone. The Rust service omits inactive flags, so the two tools name it differently — there's no `flag_disabled` reason to wait for; `flag_not_found` here means **disabled**, not a bad key. |
| `missing_dependency`                                          | The flag **depends on another flag** that isn't satisfied                                              | Dependencies fail **closed** → false. Find the parent with `feature-flags-dependent-flags-retrieve`; align/enable it (or drop the dependency).                                                                       |

"Off" isn't one state — distinguish **evaluated `false`** (a reason above), **`undefined`/`null`** (the
flag couldn't be evaluated — e.g. `missing_dependency`, or the SDK never received it), and **doesn't
exist** (wrong key). The reproduced reason tells them apart; a bare "it's off" from the customer
doesn't. One trap: `test-evaluation` returns `flag_not_found` for an **inactive** flag (the service
skips it), so don't read that as a wrong key — cross-check `active` on the config.

Expand the non-obvious ones:

- **`no_condition_match` — the property usually just doesn't match.** The single most common ticket. The
  condition references a property the user doesn't have, has under a different value/case/type
  (`"true"` string vs `true` boolean; `"US"` vs `"United States"`), or the SDK never sent it. With
  person-on-events, a property's value is what it was **at evaluation time**, not now. Confirm the
  actual value on the person, then fix the condition or the property being sent. **Caveat for
  group-targeted flags:** a group condition that was skipped (no group passed) also serializes as
  `no_condition_match`, and `evaluation-reasons` drops the detail that would distinguish it from a
  real property mismatch. Before telling a customer to change person properties, check whether the
  flag has group conditions (`aggregation_group_type_index` or a group-aggregated release condition)
  and use `test-evaluation`'s per-condition detail — if a group was skipped, the fix is passing group
  context, not changing properties (see `no_group_type`).
- **`out_of_rollout_bound` — deterministic, not random.** Assignment is a hash of the identifier, so
  a given user has a **fixed** position; they're in or out until the rollout % crosses that point.
  "It's not rolling out to me" at <100% is usually this, not a bug. (Offline rollout-gate check in
  [references/pulling-the-data.md](references/pulling-the-data.md) for the rare case you need it.)
- **`no_group_type` — the SDK didn't pass the group.** A group-aggregated flag (see
  `filters.aggregation_group_type_index`) needs the group in every evaluation call. This is a code
  fix in the customer's app, not a config change.
- **`super_condition_value` — the hidden override (early-access enrollment).** This is early-access
  feature enrollment: it early-returns before normal targeting, so a flag can be "on" for someone who
  matches no visible release condition (or off despite matching one). It's driven by
  `filters.feature_enrollment` plus the person property `$feature_enrollment/<flag_key>` (`"true"` or
  boolean `true` means enrolled; any other value means opted out) — read both when the value
  contradicts the conditions. (`filters.super_groups` is the legacy encoding; the matcher no longer
  evaluates it.)

## Known-cause catalog — "server says it matches, but the user still doesn't get it"

When `feature-flags-evaluation-reasons-retrieve` returns the **expected** value but the customer
reports otherwise, the flag is fine and the problem is in the SDK integration. Ordered by frequency:

- **Flag read before flags loaded.** The app evaluated the flag before PostHog finished loading them,
  so it got the default (`false`/`undefined`). Fix: gate on `onFeatureFlags` (posthog-js) / the
  framework's ready hook, or **bootstrap** the flags so a value exists on first paint.
- **Wrong `distinct_id` / identify timing.** The SDK evaluated under an anonymous or different
  `distinct_id` than the one you tested. If `identify()` runs _after_ the flag read, the user is
  hashed under the anonymous ID. Fix: identify before evaluating, or reload flags after `identify()`.
- **Stale local-evaluation definition.** Server-side SDKs using local evaluation refresh flag
  definitions on an interval (tens of seconds); reads during the window use the old definition.
  Signal: `locally_evaluated = true` on the usage events and a value that lags a recent flag edit.
- **Cohort not usable in the flag.** A flag can only target a **property-based** cohort. A cohort
  with **behavioral or lifecycle** filters (e.g. "did event X in the last 7 days") can't be used for
  flag targeting — the condition can't be computed at evaluation time. Signal: the release condition
  references such a cohort and the flag never matches. Fix: target person properties directly, or a
  property-only cohort.
- **Bootstrap mismatch.** Bootstrapped flags carry a value from page load; if the bootstrap payload
  used a different (or no) `distinctID` than the eventual user, the bootstrapped value can disagree
  with the server. Fix: pass the known `distinctID` in the bootstrap payload.
- **Reading the wrong thing.** `getFeatureFlagPayload()` returns the payload, not the flag value;
  `getFeatureFlag()` returns the variant string, `isFeatureEnabled()` a boolean. A multivariate flag
  read with `isFeatureEnabled()` is truthy for _any_ variant. Match the accessor to the intent.
- **Caching / ad-blockers / proxy.** `/flags` responses can be cached client-side, and ad-blockers
  drop the request entirely (value falls back to default). Fixes: a reverse proxy on the customer's
  domain, or the `flags_api_host` config option to route flag requests separately from analytics.

## Known-cause catalog — "the flag works but I see no usage" / "0 `$feature_flag_called`"

- **Usage events disabled (`send_feature_flag_events: false`).** The SDK evaluated the flag but was
  told not to emit `$feature_flag_called` (init option or per-call). The flag works; there's just no
  usage event. Fix: enable feature-flag events if you need the analytics.
- **Bulk / payload accessors don't fire usage.** `getAllFlags()` and payload-only reads don't emit
  `$feature_flag_called`. Use a single-flag accessor where you need the usage event.
- **Local evaluation without personal-API-key events.** Server-side local evaluation can suppress
  per-call events; confirm the SDK is configured to send them if usage analytics are expected.

## "Works locally but not in production" (or vice versa)

Almost always **evaluation path drift**: the browser hits `/flags` (always current) while a
server-side fleet uses **local evaluation** (definition refreshed on an interval, and blind to
behavioral/static cohorts). Compare `locally_evaluated` on the usage events across environments, and
check the local-eval refresh interval and personal-API-key setup. A flag edit that "hasn't taken
effect on the backend" is this.

## Everything else → hand off

| Customer complaint                                                                      | Route to                          |
| --------------------------------------------------------------------------------------- | --------------------------------- |
| The flag backs an experiment and the question is about results / uneven exposures / SRM | `debugging-experiments`           |
| "Which flags are stale / safe to remove?"                                               | `cleaning-up-stale-feature-flags` |
| "Copy / promote this flag to another project"                                           | `copying-flags-across-projects`   |
| "Audit our flags for hygiene / best practices"                                          | `auditing-experiments-flags`      |
| "What flags were deleted / who deleted X?"                                              | `finding-deleted-feature-flags`   |

## Access for debugging

Only investigate a project tied to a genuine support request — the IDs come from a real ticket, not
from someone asking you to look up a flag they can't point to a request for. Staff access is broad;
don't freelance across projects. **Confirm the requester actually belongs to the organization/project
before you read it.** A project ID appearing in a ticket doesn't authorize access to that project on
its own — a customer who pastes another tenant's project ID must not get its flag config, person
properties, or evaluation results back in the reply.

Prefer **read-only** paths, in this order:

1. **PostHog MCP tools** — `feature-flag-get-definition-by-key`, `feature-flag-get-all`,
   `feature-flags-evaluation-reasons-retrieve`, `feature-flags-test-evaluation-create`,
   `feature-flags-status-retrieve`, `feature-flags-activity-retrieve`,
   `feature-flags-dependent-flags-retrieve`, `feature-flags-user-blast-radius-create`,
   `execute-sql`, `persons`, `cohorts`. Read-only and the safest way to inspect config and reproduce
   an evaluation. Use this first.
2. **Flag API reads** while impersonating (staff) — for raw JSON the MCP may not surface verbatim.
3. **Django admin** only when 1 and 2 can't answer it, read-only by discipline: never edit a
   customer's flag, cohort, or person without explicit customer consent.

**Mind the instance.** An MCP session is bound to one region (US or EU) and can't query a project on
the other — an EU project is unreachable from a US-bound session. When you're blocked that way, the
read-only fallbacks are the ticket's own session recording (pull the rrweb snapshots to see what the
user's client actually received) and PostHog's own product telemetry, which the EU app reports into a
US project — enough to reconstruct the flag's edit history and usage without direct instance access.
