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

When a user mentions a specific percentage (e.g. "roll out to 25%", "test on 25% of users"), this is **always ambiguous**. You MUST ask before proceeding:

> There are two ways to get 25% of users seeing the test variant:
>
> 1. **Reduced rollout with equal split** (recommended): 50% overall rollout with a 50/50 control/test split.
>    Only 50% of users enter the experiment, and of those, half see test.
>    Result: 25% see test, 50% are in the analysis.
>    This is the recommended approach — equal splits maximize statistical power.
> 2. **Asymmetric split**: 100% overall rollout with a 75/25 control/test split.
>    All users enter the experiment, but only 25% see test.
>    Result: 25% see test, 100% are in the analysis.
>    Asymmetric splits reduce statistical power on the smaller variant.
>
> Both achieve the same user-facing outcome. The difference:
>
> - **Who sees what variant?** — same in both options
> - **Who is included in the analysis?** — option 1: 50% of users, option 2: all users
> - **Statistical power** — option 1 gives equal power to each variant; option 2 favors control
>
> Which approach do you prefer?

Adjust the numbers to match whatever percentage the user requested.

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

See `references/changing-distribution-after-launch.md` for detailed warnings, what to tell the user, and when to recommend alternatives.
