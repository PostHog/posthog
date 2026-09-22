---
name: configuring-experiment-rollout
description: Configures the rollout shape of a PostHog experiment — the variant split (50/50, 80/20, A/B/C ratios), the overall rollout percentage that gates how many users enter the experiment, and the disambiguation when a percentage like "roll out to 25%" could mean either. Use when the user mentions a rollout percentage, variant split, or traffic distribution; gives a ratio like 60/40, 70/30, or 80/20; asks "who sees the test variant?"; wants to increase, decrease, or change the rollout or split on a draft or running experiment; weighs equal vs uneven splits; or proposes a mid-experiment split change (often an anti-pattern that needs reset or end-and-restart).
---

# Configuring experiment rollout

This skill answers: **Who sees what variant?**

## Recommended approach: equal split + adjust rollout percentage

In most cases, experiments work best with an equal split. If you want to limit exposure to the test variant, adjust the rollout percentage instead.

Why equal splits are better:

- Equal splits maximize statistical power — each variant has the same sample size
- Equal splits balance traffic and thus reach significance faster
- Increasing user exposure throughout the experiment through increasing rollout is clean (changing split mid-experiment can cause users to switch variants, which is bad for user experience and data quality)

Always default to an equal split unless the user explicitly requests otherwise.

## When an uneven split is required

Uneven splits combined with the default "Exclude multivariate users" handling can introduce bias.
If the experiment observes multi-variant users (users exposed to more than one variant) then those are
dropped asymmetrically — the smaller variant loses a larger fraction of its assignments. If those users
behave differently from the rest, the smaller variant's metrics will be skewed.

The right mitigation depends on experiment state:

1. **Pre-launch, or live but with few exposures so far — use an equal split and reduce the overall
   rollout.** Achieves the same test-variant exposure without the bias and preserves statistical
   power. See the disambiguation question below.
2. **Live experiment with significant exposures — switch multivariate handling to "First seen
   variant".** Changing the split mid-run reassigns users across variants (anti-pattern; see
   "Changing rollout on a running experiment" below). Switching handling instead keeps everyone in
   their original variant and avoids the asymmetric exclusion. See `configuring-experiment-analytics`
   for how to set this. Note that "first seen" handling can introduce other biases, but it's
   preferable to mid-run reassignment.

## The two rollout controls

There are two separate controls that determine who sees what.
Both live on the linked feature flag, sent through the `feature_flag` object in the flag's own shape (not the deprecated `parameters` keys).

### 1. Variant split (`feature_flag.filters.multivariate.variants`)

How users **inside** the experiment are distributed across variants.

- Array of `{key, name, rollout_percentage}`, where the `rollout_percentage` values must sum to 100
- Minimum 2 variants, maximum 20
- No specific variant key is required — the analysis baseline defaults to the variant keyed `"control"` when present, else the first variant
- Default: control 50% / test 50%

If the user says "A/B/C test" without naming keys, key the baseline `"control"` (the convention) and create additional variants for the others; if they ask for specific keys, use them as-is with the baseline first.

### 2. Overall rollout (`feature_flag.filters.groups[0].rollout_percentage`)

What percentage of **all** users enter the experiment at all, sent as a single rollout group: `groups: [{ "properties": [], "rollout_percentage": N }]`.
Default: 100%.

Users not included are excluded entirely: they don't see any variant and are **not part of the analysis**.

### Where these are sent

Both controls live inside `feature_flag.filters`:

```json
{
  "feature_flag": {
    "filters": {
      "multivariate": {
        "variants": [
          { "key": "control", "name": "Control", "rollout_percentage": 50 },
          { "key": "test", "name": "Test", "rollout_percentage": 50 }
        ]
      },
      "groups": [{ "properties": [], "rollout_percentage": 100 }]
    }
  }
}
```

`filters` may also carry `aggregation_group_type_index` (to run the experiment on a group type rather than individual users) and `payloads` (JSON-encoded strings keyed by variant key).
On a **running** experiment, any flag-config change must also send `update_feature_flag_params: true`, otherwise the API rejects the update before it reaches the flag (see "Changing rollout on a running experiment").

### How they interact

These two controls multiply:

| Overall rollout | Variant split      | % seeing test | % in analysis |
| --------------- | ------------------ | ------------- | ------------- |
| 100%            | 50/50              | 50%           | 100%          |
| 100%            | 75/25 control/test | 25%           | 100%          |
| 50%             | 50/50              | 25%           | 50%           |
| 25%             | 50/50              | 12.5%         | 25%           |

## The disambiguation question

**CRITICAL**: If the user requests an uneven variant split (e.g. "60/40", "70/20/10") or mentions a
specific percentage that could refer to either the split or the rollout (e.g. "roll out to 25%"), you
MUST clarify before proceeding. This covers two cases:

### Case 1: Single percentage ("25%", "roll out to 40%")

The percentage is ambiguous — it could mean a variant split or a rollout change. Ask:

> There are two ways to get 25% of users seeing the test variant:
>
> 1. **Reduced rollout with equal split** (recommended): reduce the overall rollout and split
>    variants equally. Only a subset of users enter the experiment, and of those, each variant
>    gets the same share.
>    Equal splits maximize statistical power and avoid bias.
> 2. **Asymmetric split**: keep 100% rollout but give the test variant only 25%.
>    All users enter the experiment, but the uneven split reduces power on the smaller variant
>    and risks bias.
>
> Which approach do you prefer?

Adjust the numbers to match whatever percentage the user requested.

### Case 2: Uneven ratio ("60/40", "70/30", "80/20", etc.)

The ratio looks like an explicit variant split, but a reduced rollout with an equal split is almost
always better. Explain the trade-off and recommend the alternative:

> An uneven variant split works, but an equal split with reduced rollout is recommended:
>
> 1. **Equal split + reduced rollout** (recommended): reduce the overall rollout so that the same
>    fraction of users sees the test variant, but split variants equally within the experiment.
>    Equal splits maximize statistical power and avoid bias from asymmetric multivariate exclusion.
> 2. **Uneven split**.
>    Achieves the same user-facing outcome, but reduces power on the smaller variant and risks bias.
>
> Would you like the equal split approach, or do you have a specific reason for the uneven split?

Adjust the numbers to match the ratio. For experiments with more than two variants, "equal" means
each variant gets the same share (e.g. 34/33/33 for three variants). If the user confirms they want
the uneven split after seeing the trade-off, proceed — but DO NOT skip the next section.

### After the user picks the uneven split

If the user proceeds with an uneven split (option 2 in either case above), you MUST surface the
multivariate-handling implication BEFORE creating or updating the experiment. The user has chosen
the riskier rollout path and needs to make an informed choice about how to mitigate.

Ask:

> One more thing — with an uneven split, the default "Exclude multivariate users" handling drops
> users exposed to multiple variants asymmetrically. The smaller variant loses a larger fraction of
> its assignments, which can skew its metrics if those users behave differently from the rest.
>
> Two options:
>
> 1. **Switch multivariate handling to "First seen variant"** (recommended for uneven splits) —
>    keeps all users in the analysis and avoids asymmetric exclusion. Has its own caveats (other
>    biases can creep in) but is preferable to the default for uneven splits.
> 2. **Keep the default "Exclude" handling** and accept the bias risk.
>
> Which would you like?

See `configuring-experiment-analytics` for how to set the multivariate handling. Apply the choice
as part of the same operation (creation or update) — do not leave the user with an uneven split
under default handling without an explicit, informed decision.

## Bucketing and persistence across login

By default a person's variant follows their distinct ID. When the same person sees the flag before and after they are identified (usually at login), their distinct ID changes, and so can their variant.
Choose at creation; never change bucketing or persistence on a live flag. In this order:

1. **Page seen mostly by one kind of visitor** (almost all anonymous, or almost all identified): keep user-id bucketing and leave `ensure_experience_continuity` out, so the team's persistence default applies.
2. **Page crosses identification, and every flag call carries a device ID**: use device-id bucketing (recipe below). A flag call without a device ID gets no variant, so a server SDK must forward the browser's device ID. Local evaluation works when it does. The web SDK sends the device ID on flag requests from posthog-js 1.307.1; check the version, because an older one puts a device ID on events but not on flag requests.
3. **Page crosses identification, and no SDK evaluates the flag locally**: persist the flag (`ensure_experience_continuity: true`). Persistence needs person profiles for anonymous users, no bootstrapping, and `$anon_distinct_id` on server flag calls. Learn more: https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps
4. **Otherwise**: keep user-id bucketing and tell the user what would unlock the other options (a device ID on every flag call, or no local evaluation).

When `ensure_experience_continuity` is omitted, `experiment-create` applies the team's persistence default. Set it to `false` only when that default is `true` and local evaluation rules persistence out. The device-id recipe needs no such step: `create-feature-flag` leaves persistence off unless you set it, and `experiment-create` rejects a `feature_flag` object for a flag that already exists. Device-id bucketing and persistence can't be combined.

### Device-id bucketing recipe

`experiment-create` cannot set bucketing, so create the flag first, then link it:

1. Call `create-feature-flag` with the experiment's key, `bucketing_identifier: "device_id"`, and `active: false` so no one gets a variant before launch (a new flag is active by default):

   ```json
   {
     "key": "kebab-case-key",
     "name": "Experiment name",
     "active": false,
     "bucketing_identifier": "device_id",
     "filters": {
       "groups": [{ "properties": [], "rollout_percentage": 100 }],
       "multivariate": {
         "variants": [
           { "key": "control", "rollout_percentage": 50 },
           { "key": "test", "rollout_percentage": 50 }
         ]
       }
     }
   }
   ```

   `filters.groups` is required: a flag without a group is rejected.

2. Call `experiment-create` with that `feature_flag_key` and no `feature_flag` object. The experiment links the flag as it is, and launching the experiment turns the flag on.

`experiment-setup-context` reports the facts these rules need (the page's share of unidentified visitors, and per SDK the device-ID and local-evaluation shares). `creating-experiments` (`references/setup-decisions.md`) applies them.

## Resolving experiments

Rollout changes require an experiment ID. If the user refers to an experiment by name
or description (e.g. "change rollout on my signup test"), load the `finding-experiments`
skill to resolve it to a concrete ID before proceeding.

## Changing rollout on a running experiment

**Any change to rollout or variant split on a running experiment affects both user experience and statistical validity.**
You MUST warn the user and get explicit confirmation before making the change.

Do NOT silently apply the change — even if the user asked for it directly.
Present the warning covering both perspectives:

1. **Who sees what variant?** — will users switch variants or lose a feature?
2. **Who is in my analysis?** — how does this affect data quality?

**Exception**: Increasing rollout (without changing the split) is generally safe — no users switch variants, more users are added cleanly.

**If the goal is "stop new users from entering" rather than a percentage change**: reducing the rollout is the wrong tool — it drops already-enrolled users out of the experiment too.
Freezing exposure (`experiment-freeze-exposure`) closes enrollment while enrolled users keep their variant and metrics keep flowing; see `managing-experiment-lifecycle` for its preconditions and limitations.

**Mid-experiment fix for uneven-split bias**: switching multivariate handling from "Exclude" to "First
seen variant" is the recommended mitigation for already-launched experiments — no users switch variants
and all collected data stays in the analysis. Changing the split to be even is an anti-pattern mid-run
(typically requires resetting or ending the experiment) and is only preferred if the experiment hasn't
been exposed to many users yet. See `configuring-experiment-analytics` for how to change the handling.

See `references/changing-distribution-after-launch.md` for detailed warnings, what to tell the user, and when to recommend alternatives.

## Related skills

- **`configuring-experiment-analytics`** — the analysis side: exposure criteria, metrics, and multivariate handling
- **`diagnosing-experiment-results`** — when a mid-run split change has already skewed the results
- **`managing-experiment-lifecycle`** — reset or end-and-restart mechanics when a split change requires them
