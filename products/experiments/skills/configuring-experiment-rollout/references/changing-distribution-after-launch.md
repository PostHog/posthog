# Changing distribution after launch

Any change to rollout or variant split on a running experiment affects both **user experience** and **statistical validity**. You MUST warn the user and get explicit confirmation before making the change.

Further reading: https://posthog.com/docs/experiments/changing-distribution-after-rollout

Always frame the impact through both questions:

1. **Who sees what variant?** (user perspective)
2. **Who is included in my analysis?** (statistical perspective)

## Increasing rollout (safe)

Example: 20% rollout → 80% rollout, same 50/50 split.

**User experience**: Users already in the experiment see no change — they keep their variant. New users from the previously-excluded 60% are added: half go to control, half to test. No one switches variants. This is the safest change.

**Analysis**: More users enter the experiment, increasing statistical power. No bias introduced — the existing population is untouched, new users are cleanly randomized.

**Verdict**: This is the one change that's generally safe to make on a running experiment.

## Decreasing rollout (use caution)

Example: 80% rollout → 50% rollout.

**User experience**: Some users who were in the experiment are now excluded. Users who were in the control variant (A) won't notice — they already saw the default behavior. But users who were in the test variant (B) and fall in the removed bucket **will switch back to the default experience**. This is a visible UX disruption — they had the new feature and now it disappears.

**Analysis**: Users who were already exposed to a variant continue to be counted in the analysis based on their prior exposure. Even revoking to 0% rollout still shows metrics from prior exposures. But the mixed experience (saw B, then switched to default) makes their behavior data noisy.

**Warning to present**:

> Decreasing rollout will cause some users currently seeing the test variant to switch back to the default experience. This is a visible change for those users — the feature they had will disappear. Their data also becomes harder to interpret statistically.

## Changing the variant split (anti-pattern)

Example: 50/50 split → 80/20 A/B split.

**User experience**: This moves the bucket boundaries. Users who were previously assigned to B may now fall in A's expanded bucket. When rollout is increased later, **these users switch from the test variant back to control** — they see a different experience than what they were originally assigned. This is the most disruptive change because it causes variant reassignment.

**Analysis**: Users who experienced B and are now in A have behavior that can't be cleanly attributed to either variant — this is bias. PostHog handles this with two options:

- **Exclude multivariate users** (default, recommended) — removes these users from the analysis. Cleaner data but fewer data points, meaning longer time to reach reliable results.
- **First seen variant** — keeps all users, attributes them to their first variant. More data but noisier.

**Warning to present**:

> **Changing the variant split on a running experiment is an anti-pattern.** It moves bucket boundaries, which can cause users to be reassigned between variants — they see a different experience than before. This introduces statistical bias and degrades the user experience.
>
> Alternatives:
>
> - **Reset the experiment** if it's early and little data has been collected
> - **End this experiment and start a new one** if significant data exists — preserves your existing results cleanly
>
> Do you still want to proceed?

## Adding variants after rollout (anti-pattern)

Example: Adding variant C to a running A/B experiment.

**User experience**: Users may bounce between variants (B → C). This is likely the worst UX outcome — the experience changes unpredictably.

**Analysis**: More multivariate users to exclude, AND more variants means more traffic needed for reliable results. You're simultaneously reducing your usable data AND increasing the amount you need. This compounds badly.

**This is not supported on running experiments** — PostHog prevents adding or removing variants on non-draft experiments. Only rollout percentages between existing variants can change.

## What to recommend

| Change               | Safe?        | UX impact                      | Statistical impact                       |
| -------------------- | ------------ | ------------------------------ | ---------------------------------------- |
| Increase rollout     | Yes          | None — new users added cleanly | More data, no bias                       |
| Decrease rollout     | Caution      | Test users lose the feature    | Noisy data from switched users           |
| Change variant split | Anti-pattern | Users may switch variants      | Bias from reassignment                   |
| Add/remove variants  | Blocked      | N/A                            | N/A (not allowed on running experiments) |

**Best practice** from the docs: the ideal experiment has equal split between variants and no changes after launch other than increasing the total rollout.

## Technical requirements

Both changes on running experiments **require** `update_feature_flag_params: true` in the request.
Without it, changes save on the experiment object but do NOT sync to the feature flag — so they have no effect on actual variant assignment.

Draft experiments sync automatically — this flag is only needed for running experiments.
