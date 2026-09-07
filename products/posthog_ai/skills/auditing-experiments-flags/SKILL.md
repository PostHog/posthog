---
name: auditing-experiments-flags
description: 'Audit PostHog experiments and feature flags for configuration issues, staleness, and best-practice violations. Read when the user asks to audit, health-check, or review experiments or feature flags, check flag hygiene, or verify experiment setup.'
---

# Auditing experiments and feature flags

This skill teaches you how to run configuration audits on experiments and feature flags.
All checks use the experiment and feature flag read tools (`experiment-get`, `experiment-list`, `feature-flag-get-definition`, `feature-flag-get-all`) — no SQL queries are needed for Phase 1 checks.

The two list tools return thin summaries. Use them to resolve IDs only.
Every check reads fields that appear on the full object alone, such as `metrics`, `parameters`, `filters.multivariate`, `experiment_set`, and `last_called_at`.
Always fetch each entity via `experiment-get` or `feature-flag-get-definition` before you run a check.
A check that runs on a list payload reads empty fields and reports nothing.

Both list tools are paginated and return at most 100 entities per page.
Page through them until `next` is null, advancing `offset` by the number of results each call returns.
Compare the IDs you collected with `count` before you run a check, and report the audit as partial if you could not reach the end.

## Usage modes

### Quick check (single entity)

When the user asks about a specific experiment or flag:

1. Fetch the entity via `experiment-get` (experiment ID) or `feature-flag-get-definition` (numeric flag ID).
2. Apply the relevant checks from [experiment checks](./references/experiment-checks.md) or [flag checks](./references/flag-checks.md).
3. Report findings inline as markdown, grouped by severity (CRITICAL first, then WARNING, then INFO).
4. Include entity links as `[Experiment: name](/experiments/id)` or `[Flag: key](/feature_flags/id)`.

### Scoped audit (one domain)

When the user asks to audit all experiments or all flags:

1. Resolve the entity IDs via `experiment-list` or `feature-flag-get-all`.
2. For each ID, fetch the full entity via `experiment-get {id}` or `feature-flag-get-definition {id}`.
3. Run all checks for that domain against each fetched entity.
4. Group findings by severity, then by entity.
5. Report as inline markdown.

### Full audit (comprehensive)

When the user asks for a comprehensive audit of both experiments and flags:

1. Resolve all experiment IDs via `experiment-list` and all flag IDs via `feature-flag-get-all`.
2. Fetch each experiment via `experiment-get {id}` and each flag via `feature-flag-get-definition {id}`.
3. Run all experiment checks and all flag checks against the fetched entities.
4. Apply [recurring patterns](./references/synthesis-patterns.md) to identify patterns across multiple findings.
5. If there are more than 5 entities with findings, write them to a notebook for easier navigation. Otherwise report inline. Create the notebook from the project's own notebook tools. Run `search notebooks?-` to load them and read the titles.

## Output format

For each finding, include:

- **Severity badge**: `🔴 CRITICAL`, `🟡 WARNING`, or `🔵 INFO`
- **Check name**: Which check produced this finding
- **Entity link**: Markdown link to the entity
- **What's wrong**: One-sentence description
- **Action**: What to do about it (see [remediation actions](./references/remediation-actions.md))

Example:

> 🟡 **WARNING** — Flag integration · [Experiment: checkout-redesign](/experiments/42)
> This experiment is running but its linked feature flag is inactive, so traffic is not being split.
> **Action**: Re-enable the flag to resume, or end the experiment.

## Handling unavailable data

Some checks require activity logs (`feature-flags-activity-retrieve` for flags), which may not be available in every session.
If activity log data is unavailable:

- Skip `checkActivityHistory` (experiment check) entirely.
- Skip the "toggle instability" and "never activated" sub-checks in flag lifecycle checks.
- In your report, note which checks were skipped and why:
  > _Skipped: Activity history checks (activity logs not available via current tools)_

## Partial failures

If a fetch call fails for some entities:

- Continue with the entities you could fetch.
- Report which entities could not be assessed and why.
- Do not silently omit entities from the audit.

## Reference files

- [Experiment checks](./references/experiment-checks.md) — experiment configuration checks
- [Flag checks](./references/flag-checks.md) — feature flag checks
- [Finding types](./references/finding-taxonomy.md) — severity and category definitions
- [Recurring patterns](./references/synthesis-patterns.md) — patterns across multiple findings
- [Remediation actions](./references/remediation-actions.md) — what to do about each finding
