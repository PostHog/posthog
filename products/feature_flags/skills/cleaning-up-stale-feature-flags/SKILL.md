---
name: cleaning-up-stale-feature-flags
description: 'Identify and clean up stale feature flags in a PostHog project. Use when the user wants to find unused, fully rolled out, or abandoned feature flags, review them for safety, and then disable or delete them. Covers staleness detection, dependency checking, and safe removal workflows.'
---

# Cleaning up stale feature flags

This skill guides you through finding feature flags that are no longer serving a purpose and safely removing them.

## When to use this skill

- The user asks to clean up, audit, or review their feature flags
- The user wants to find flags that are stale, unused, or fully rolled out
- The user asks "which feature flags can I remove?" or similar
- The user wants to reduce tech debt from old feature flags

## What makes a flag stale

A feature flag is considered stale when it's no longer doing useful work. PostHog tracks this with two signals:

1. **Usage-based staleness**: The flag has `last_called_at` data, but hasn't been evaluated in 30+ days. This is the strongest signal — the SDKs are no longer checking this flag.
2. **Configuration-based staleness**: The flag has no usage data (`last_called_at` is null), is 30+ days old, and is 100% rolled out (boolean at 100% with no property filters, or a multivariate flag with one variant at 100%). A fully rolled out flag with no conditions is equivalent to a hardcoded value — it can be replaced by removing the flag check from code.

Disabled flags (`active: false`) are not considered stale — they were intentionally turned off and may be kept for reactivation.

## Workflow

### 1. List stale flags

Call `posthog:feature-flag-get-all` with `active: "STALE"`. This returns all stale flags in a single request — PostHog handles the staleness detection server-side using the criteria described above.

### 2. Assess each candidate

For each stale flag, gather context before recommending action:

**Check if it's tied to an experiment:**

The `posthog:feature-flag-get-definition` tool returns an `experiment_set` field. If non-empty, the flag is used by an experiment — check the experiment status before touching it.

**Check if other flags depend on it:**

Feature flags can have dependencies (flag B only evaluates when flag A is true). The flag definition includes dependency information in its `filters`. Look for `flag_key` references in other flags' filter groups.

**Check when it was last modified:**

A flag last updated years ago with no recent calls is a stronger removal candidate than one updated last month with no calls (it might be newly deployed and waiting for a release).

**Summarize for the user:**

For each stale flag, present:

- Flag key and description
- Why it's considered stale (no calls in N days, or fully rolled out for N days)
- Whether it's tied to experiments
- When it was created and last modified
- A recommended action (disable, delete, or keep with explanation)

### 3. Take action (with user confirmation)

**Never delete or disable flags without explicit user approval.** Always present the list and recommendations first, then ask which flags to act on.

**Disable first, delete later:**

The safest approach is a two-phase cleanup:

1. **Disable** the flag (`active: false`) using `posthog:update-feature-flag`. This stops it from being evaluated but keeps the configuration intact. If something breaks, re-enabling is instant.
2. **Delete** the flag using `posthog:delete-feature-flag` after the user confirms no issues. This is a soft-delete — the flag is marked as deleted but not physically removed.

When disabling or deleting multiple flags, process them one at a time and confirm each action. This makes it easy to stop if something goes wrong.

### 4. Generate code cleanup instructions

After disabling or deleting flags, generate a cleanup prompt the user can run in their code editor or coding agent. The cleanup instructions must be tailored to each flag's rollout state, because the rollout state determines which code path to keep.

Classify each deleted/disabled flag into one of three rollout states based on its definition:

- **`fully_rolled_out`**: A boolean flag with a release condition at 100% rollout and no property filters, or a multivariate flag where one variant is at 100%. Record which variant was active (for multivariate flags).
- **`not_rolled_out`**: All release conditions are at 0%, or the flag has no release conditions at all.
- **`partial`**: Everything else — the flag had some targeting but wasn't fully rolled out or fully off.

Then generate instructions following this structure:

**For fully rolled out boolean flags** — remove the flag check but keep the enabled code path:

```text
Search for: isFeatureEnabled, useFeatureFlag, getFeatureFlag, posthog.isFeatureEnabled, posthog.getFeatureFlag

For flag "example-flag":
- Remove the if-check, keep the body
- If there is an else branch, remove the else branch entirely
```

**For fully rolled out multivariate flags** — keep only the winning variant's code:

```text
For flag "example-flag" (keep variant: "winning-variant"):
- For if/else chains: keep only the branch matching "winning-variant", remove the flag check
- For switch statements: keep only the winning variant's case, remove the switch
```

**For not-rolled-out flags** — remove the entire flag check AND the enabled code path:

```text
For flag "example-flag":
- Remove the if-check AND its body (the feature was never active)
- If there is an else branch, keep only the else body
```

**For partial rollout flags** — flag these for manual review:

```text
For flag "example-flag":
- This flag had a partial rollout — check the flag's intent to determine which code path to keep
- Then remove the flag check
```

End the instructions with: "After cleanup, remove any dead code branches and unused imports."

Present the full cleanup prompt in a copyable format so the user can paste it directly into Claude Code, Cursor, Copilot, or any other AI code editor. This is the same approach used in the PostHog UI's bulk delete flow.

## Example interaction

```text
User: "Can you help me clean up our stale feature flags?"

Agent steps:
- Call posthog:feature-flag-get-all with active: "STALE" to get all stale flags in one request
- For each stale flag, call posthog:feature-flag-get-definition to check experiment_set and dependencies
- Present findings:

   "I found 7 stale feature flags in your project:

   | Flag | Last called | Reason | Recommendation |
   |------|-------------|--------|----------------|
   | old-checkout-flow | 45 days ago | No evaluations in 45 days | Disable then delete |
   | beta-dashboard-v2 | Never | 100% rolled out, created 3 months ago | Disable then delete |
   | holiday-promo-2024 | 90 days ago | No evaluations in 90 days | Delete (seasonal, won't reuse) |
   | new-pricing-page | 60 days ago | No evaluations in 60 days, tied to experiment #42 | Check experiment first |
   ...

   Want me to disable any of these? I'd recommend starting with old-checkout-flow
   and beta-dashboard-v2 since they have no dependencies."

- User confirms: "Yes, remove those two"
- Disable each flag first using posthog:update-feature-flag (active: false), then confirm with the user before deleting
- After user confirms no issues, call posthog:delete-feature-flag for each
- Classify rollout states from the flag definitions:
   - old-checkout-flow: fully_rolled_out (boolean, 100% rollout, no conditions)
   - beta-dashboard-v2: fully_rolled_out (boolean, 100% rollout, no conditions)
- Generate and present cleanup prompt:

   "Both flags are deleted. Here's a cleanup prompt you can paste into your
   code editor:

   ---
   Find and remove all references to these deleted feature flags in the codebase.
   For each flag, search for all usages: isFeatureEnabled, useFeatureFlag,
   getFeatureFlag, posthog.isFeatureEnabled, posthog.getFeatureFlag, etc.

   ## Flags that were rolled out to 100%
   These flags were fully rolled out. Remove the flag check but KEEP the enabled code path.

   Boolean flags (remove the if-check, keep the body):
   - old-checkout-flow
   - beta-dashboard-v2

   If there is an else branch, remove the else branch entirely.
   After cleanup, remove any dead code branches and unused imports.
   ---"
```

## Important notes

- **Always confirm before acting.** This skill involves disabling and deleting flags, which can affect production behavior.
- **Disabled flags are not stale.** Don't recommend deleting flags that are intentionally disabled — they may be kept for emergency reactivation.
- **Experiment flags need extra care.** If a flag is tied to an active or recently completed experiment, the user likely wants to keep it until they've analyzed results.
- **Seasonal flags may return.** Flags like "black-friday-sale" might look stale but are intentionally reused. Ask the user before removing these.
- **Code cleanup is the real win.** Removing the flag from PostHog is the easy part. The value comes from removing the dead code paths.

## Related tools

- `posthog:feature-flag-get-all`: List and search feature flags (supports `active: "STALE"` filter)
- `posthog:feature-flag-get-definition`: Get full flag details including experiment associations
- `posthog:feature-flags-status-retrieve`: Get the status and reason for a single flag
- `posthog:update-feature-flag`: Disable a flag by setting `active: false`
- `posthog:delete-feature-flag`: Soft-delete a flag
