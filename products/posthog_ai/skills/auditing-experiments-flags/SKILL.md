---
name: auditing-experiments-flags
description: 'Audit PostHog experiments and feature flags for configuration issues, staleness, and best-practice violations. Read when the user asks to audit, health-check, or review experiments or feature flags, check flag hygiene, or verify experiment setup.'
---

# Auditing experiments and feature flags

This skill teaches you how to run configuration audits on experiments and feature flags.
All checks use `read_data` and `list_data` — no SQL queries are needed for Phase 1 checks.

## Usage modes

### Quick check (single entity)

When the user asks about a specific experiment or flag:

1. Fetch the entity via `read_data` (e.g., `read_data("experiments", id)` or `read_data("feature_flags", id)`).
2. Apply the relevant checks from [experiment checks](./references/experiment-checks.md) or [flag checks](./references/flag-checks.md).
3. Report findings inline as markdown, grouped by severity (CRITICAL first, then WARNING, then INFO).
4. Include entity links as `[Experiment: name](/experiments/id)` or `[Flag: key](/feature_flags/id)`.

### Scoped audit (one domain)

When the user asks to audit all experiments or all flags:

1. Bulk-fetch via `list_data` (e.g., `list_data("experiments")` or `list_data("feature_flags")`).
2. Run all checks for that domain against each entity.
3. Group findings by severity, then by entity.
4. Report as inline markdown.

### Full audit (comprehensive)

When the user asks for a comprehensive audit of both experiments and flags:

1. Fetch all experiments via `list_data("experiments")` and all flags via `list_data("feature_flags")`.
2. Run all experiment checks and all flag checks.
3. Apply [recurring patterns](./references/synthesis-patterns.md) to identify patterns across multiple findings.
4. If there are more than 5 entities with findings, output as a notebook artifact via `create_notebook` for easier navigation. Otherwise report inline.

## Output format

For each finding, include:

- **Severity badge**: `🔴 CRITICAL`, `🟡 WARNING`, or `🔵 INFO`
- **Check name**: Which check produced this finding
- **Entity link**: Markdown link to the entity
- **What's wrong**: One-sentence description
- **Action**: What to do about it (see [remediation actions](./references/remediation-actions.md))

Example:

> 🟡 **WARNING** — Flag integration · [Experiment: checkout-redesign](/experiments/42)
> The linked feature flag is inactive (paused). Traffic is not being split.
> **Action**: Re-enable the flag or end the experiment.

## Handling unavailable data

Some checks require activity logs, which may not be available via `read_data`.
If activity log data is unavailable:

- Skip `checkActivityHistory` (experiment check) entirely.
- Skip the "toggle instability" and "never activated" sub-checks in flag lifecycle checks.
- In your report, note which checks were skipped and why:
  > _Skipped: Activity history checks (activity logs not available via current tools)_

## Partial failures

If a `read_data` or `list_data` call fails for some entities:

- Continue with the entities you could fetch.
- Report which entities could not be assessed and why.
- Do not silently omit entities from the audit.

## Reference files

- [Experiment checks](./references/experiment-checks.md) — experiment configuration checks
- [Flag checks](./references/flag-checks.md) — feature flag checks
- [Finding types](./references/finding-taxonomy.md) — severity and category definitions
- [Recurring patterns](./references/synthesis-patterns.md) — patterns across multiple findings
- [Remediation actions](./references/remediation-actions.md) — what to do about each finding
