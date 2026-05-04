---
name: copying-flags-across-projects
description: 'Copy a feature flag from one PostHog project to one or more target projects in the same organization. Use when the user wants to duplicate a flag, promote a flag from staging to production, sync flags across projects, or replicate a flag configuration in a different workspace. Covers cohort remapping, scheduled-change handling, encrypted payloads, and the safe defaults (disabled in target, no scheduled changes).'
---

# Copying feature flags across projects

This skill guides you through duplicating a feature flag from a source project into one or more target projects within the same PostHog organization.

## When to use this skill

- The user asks to "copy a flag to another project", "duplicate this flag", or "sync a flag between projects"
- The user wants to promote a flag from a staging project to a production project (or vice versa)
- The user wants to replicate a flag configuration in a different workspace and keep cohort dependencies intact
- The user is working around the absence of true environments by using projects-as-environments

## What this skill does not cover

- **Cross-organization copy** is not supported. The endpoint requires source and target projects to belong to the same org.
- **Bulk copying every flag in a project**. The tool copies one flag at a time. For batch copies, loop through flag keys; each call is independent.
- **Cleaning up old or stale flags** — see the `cleaning-up-stale-feature-flags` skill instead.

## Workflow

### 1. Resolve the source flag

You need the flag's **key** and the **source project's id**.

- If the user gave a flag key and a project id, use them directly.
- If the user gave a flag name (e.g. "the new pricing flag"), call `posthog:feature-flag-get-all` in the source project to find the matching flag and read its `key`.
- If the user only gave a flag and not a project, ask which project it lives in. Don't assume the active MCP project — copying out of the wrong source is a common foot-gun.

### 2. Resolve target project ids

Targets must be in the same organization as the source. Call `posthog:projects-get` to list available projects and confirm membership before issuing the copy.

For a multi-target copy, the tool accepts up to 50 target project ids in a single call. Successes and failures are reported per target, so a partial failure does not block the rest.

### 3. Preview the source flag

Call `posthog:feature-flag-get-definition` on the source flag and present a concise summary to the user before copying:

- Flag key, name, and active state in the source
- Filter groups (rollout %, property filters, variant splits)
- Any cohort references in `filters.groups[].properties[]` — these will be remapped server-side, but the user should know whether the target project already has matching cohorts
- Whether the flag has encrypted payloads (`has_encrypted_payloads`) or is remote configuration (`is_remote_configuration`)
- Whether scheduled changes exist (the user can opt to copy them in step 4)

### 4. Confirm copy options

Default to the safest combination and ask the user to override only if they explicitly want different behavior:

- **`disable_copied_flag: true`** — the copied flag lands disabled in the target. Recommended by default; turning a flag on in a new project should be a deliberate, observed action.
- **`copy_schedule: false`** — scheduled changes do not come along. Recommended by default; schedules are usually project-specific.

If the user says "promote it as-is" or "turn it on in prod", switch `disable_copied_flag` to `false`. If they say "include the rollout schedule" or "with the scheduled rollout", switch `copy_schedule` to `true`.

### 5. Execute the copy

Call `posthog:feature-flags-copy-flags-create` with:

- `feature_flag_key`: the source flag's key
- `from_project`: the source project id
- `target_project_ids`: the resolved list of target project ids
- `disable_copied_flag`: from step 4 (default `true`)
- `copy_schedule`: from step 4 (default `false`)

### 6. Report per-target outcome

The response includes a `success` array (one entry per copied flag) and a `failed` array (per-target errors). Surface both:

- For each success: target project id, the new flag's id, and its `active` state in the target.
- For each failure: target project id and the error message. Common causes are missing editor access on the target team, or the flag already existing as a non-overridable resource in the target.

If any targets failed, ask the user whether to retry the failed ones, skip them, or fix the underlying issue (e.g. grant access, then retry).

## Important notes

- **Cohorts are remapped automatically.** When the source flag references a cohort, the endpoint creates or reuses an equivalent cohort in each target project and rewrites the flag's filters to point at the target-project cohort id. You don't need to handle this — but tell the user it's happening so they understand the new cohorts that may appear in the target.
- **Encrypted payloads are preserved.** Remote-configuration flags with encrypted payloads keep their encryption when copied; the payload is re-encrypted under the target project's key.
- **Scheduled changes copy with cohort remap too.** If `copy_schedule: true`, any scheduled cohort references are remapped just like the live filter conditions.
- **Auth requirements.** The user's API key must include explicit `feature_flag:write` (or `feature_flag:*`) scope. A `*`-only key will be rejected — this endpoint is gated by an INTERNAL viewset and `*` consent does not satisfy it. Team-scoped keys cannot reach this endpoint either; an org-scoped or unscoped key is required.
- **Editor access on the source.** The user must have at least editor-level access on the source flag's team. The endpoint enforces this via PostHog's access control before copying.
- **Per-target access on targets.** Targets the user can't see are silently dropped from the result; targets they can see but lack edit rights on appear in the `failed` array with a permission error.
- **No undo.** A copy creates a new flag in the target (or overwrites an existing flag with the same key). Always confirm with the user before issuing the copy, especially when the target is a production project.

## Example interaction

> **User:** Copy the `new-checkout` flag from project 12345 to project 67890.
>
> **Agent:** Looking at the source flag in project 12345.
>
> _(calls `posthog:feature-flag-get-definition`)_
>
> The `new-checkout` flag is currently a boolean at 25% rollout in project 12345, with no cohort filters and no scheduled changes. I'll copy it as **disabled** in project 67890 with no scheduled changes — this is the safer default. Confirm?
>
> **User:** Yes, but enable it in the target.
>
> **Agent:** Got it — enabling in the target.
>
> _(calls `posthog:feature-flags-copy-flags-create` with `disable_copied_flag: false`, `copy_schedule: false`)_
>
> Done. Created flag id 99887 in project 67890 (`active: true`). No failed targets.

## Available tools

- `posthog:feature-flags-copy-flags-create` — performs the copy. Required fields: `feature_flag_key`, `from_project`, `target_project_ids`. Optional: `disable_copied_flag`, `copy_schedule`.
- `posthog:feature-flag-get-all` — find a flag by key/name in a given project when the user only gave a friendly name.
- `posthog:feature-flag-get-definition` — fetch the full source flag (filters, variants, cohort references, encryption flags) so you can preview before copying.
- `posthog:projects-get` — list projects in the active organization, used to resolve and validate target project ids.
