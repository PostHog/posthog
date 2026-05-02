---
name: configuring-experiment-rollout
description: "Guides rollout configuration for experiments: variant splits, overall rollout percentage, and the critical disambiguation when a user mentions a specific percentage. Covers both initial setup and mid-experiment changes.\nTRIGGER when: user mentions a rollout percentage, asks about variant splits, wants to change distribution on a running experiment, or asks 'who sees what variant?'\nDO NOT TRIGGER when: user is asking about metrics, analytics, or experiment results."
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

There are two separate controls that determine who sees what. Both are set via `parameters`.

### 1. Variant split (`parameters.feature_flag_variants`)

How users **inside** the experiment are distributed across variants.

- Array of `{key, name, split_percent}` — percentages must sum to 100
- First variant must have key `"control"` — this is the baseline
- Minimum 2 variants, maximum 20
- Default: control 50% / test 50%

If the user says "A/B/C test", map the baseline to `"control"` and create additional variants for the others.

### 2. Overall rollout (`parameters.rollout_percentage`)

What percentage of **all** users enter the experiment at all. Default: 100%.

Users not included are excluded entirely — they don't see any variant and are **not part of the analysis**.

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

## Persist flag across authentication steps

This option (`ensure_experience_continuity` on the feature flag) is only relevant when:

- The feature flag is shown to **both** logged-out AND logged-in users
- You need the same variant assignment before and after login

This is not compatible with all setups. Learn more: https://posthog.com/docs/feature-flags/creating-feature-flags#persisting-feature-flags-across-authentication-steps

Only mention this to the user if their use case involves pre/post-authentication experiences.

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

**Mid-experiment fix for uneven-split bias**: switching multivariate handling from "Exclude" to "First
seen variant" is the recommended mitigation for already-launched experiments — no users switch variants
and all collected data stays in the analysis. Changing the split to be even is an anti-pattern mid-run
(typically requires resetting or ending the experiment) and is only preferred if the experiment hasn't
been exposed to many users yet. See `configuring-experiment-analytics` for how to change the handling.

See `references/changing-distribution-after-launch.md` for detailed warnings, what to tell the user, and when to recommend alternatives.
