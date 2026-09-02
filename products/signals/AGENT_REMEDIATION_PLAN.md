# Self-driving inbox: agent remediation flow

Follow-on to PR #92769.

## Goal

Let an internal task or an external coding agent claim an actionable report, show that work is underway, and optionally attach one implementation pull request. External-agent remediation must not require a task or any task-backed data.

## Actor model

Assignments and report artefacts use four actor kinds:

- `user`: a person acting directly through PostHog or the API.
- `task`: an internal PostHog task. This is the only actor kind that references the tasks product.
- `agent`: an external MCP coding agent acting on behalf of an authenticated user.
- `system`: an automated PostHog process.

For MCP requests without an internal task header, the backend derives the agent name from the MCP client identity forwarded by the MCP server. The authenticated user remains the principal. The client name is attribution metadata, not an authorization boundary.

Existing artefacts are not backfilled. A null actor kind on a legacy row is read as `system`.

## Claim behavior

`inbox-reports-claim` accepts:

- `report_id`
- optional `pr_url`
- optional `release`, defaulting to `false`

Claiming upserts the current assignment. A new actor silently takes over an existing claim. Repeating an identical claim is idempotent.

`release=true` clears only the owner. It keeps an attached PR and its state. Only the current actor may release a claim. A request cannot combine `release=true` with `pr_url`.

Claims do not expire. Expiration and heartbeats are deferred.

Reports in `ready`, `pending_input`, `potential`, or `suppressed` may be claimed. Resolved reports remain terminal.

## Pull requests

A report has at most one attached implementation PR. One PR may be attached to several reports.

The assignment stores the supplied URL and its normalized `(repository, pr_number)` identity. Replacing the URL updates the assignment and records the before/after values in the activity log.

When the repository is connected, attaching a PR immediately fetches its state. Open and draft PRs put the report in review. A merged PR resolves the report. A closed, unmerged PR suppresses it, matching the existing inbox behavior.

PRs from unconnected repositories are allowed. Their state is `unknown`, they are treated as in review, and they require a manual state transition because PostHog cannot fetch their state or receive their webhooks.

GitHub webhook matching is scoped by the teams associated with the installation, then matched by normalized repository and PR number. A matching merge or close transitions every unresolved report attached to that PR.

Resolving a report never requires a PR. Manual resolution keeps the existing behavior: `fixed_outside_posthog` describes a fix without a PR, and `pr_merged` describes a merged PR that did not resolve the report automatically. A direct resolve or suppression closes an attached open PR when PostHog can access it.

## Derived work state

Work state is derived in this order:

1. `done`: the report is resolved.
2. `in_review`: an attached PR is open, draft, or unknown.
3. `working`: the report has an owner and no in-review PR.
4. `unclaimed`: the report has no owner and no in-review PR.

Pipeline `status` and remediation `work_state` remain separate. Claimed reports still appear in actionable views.

## Data model

Add `SignalReportAssignment`, one row per report:

- team and report
- nullable actor kind, authenticated user ID, internal task ID, and external agent name
- optional PR URL, normalized repository and PR number
- optional PR state and merged flag
- `claimed_at`, `created_at`, and `updated_at`

Ownership fields are nullable so release can preserve PR state. External-agent rows never carry a task ID.

Add `actor_kind` and `actor_agent` to `SignalReportArtefact`. Keep `created_by` and `task`. New writes persist explicit actor kinds; legacy null kinds serialize as `system`.

## API and MCP surface

- Add `inbox-reports-claim` for claim, takeover, PR attachment, PR replacement, and release.
- Keep `inbox-reports-set-state` for resolve, suppress, and restore.
- Extend `inbox-reports-list` with `unclaimed` and `assignee=me` filters.
- Return `work_state`, assignment actor details, `claimed_at`, PR URL, and PR state from every report list and retrieve response.
- Back `has_implementation_pr`, `implementation_pr_url`, and `implementation_pr_merged` from the assignment table.
- Update list and retrieve agent guidance to claim before starting work. External agents no longer need or create a task association.

`assignee=me` means the exact current actor: the authenticated user for direct user requests, or the authenticated user plus derived MCP client name for external agents.

## Audit trail

Use the existing `ActivityLog` mechanism with `scope=SignalReport`. Record claim, takeover, release, PR attachment, and PR replacement as before/after assignment changes. Do not write an entry for an identical repeat request.

No new assignment-history table or assignment artefact type is required.

## Deferred work

- Claim expiration and heartbeats.
- Force-takeover or compare-and-swap ownership.
- More than one PR per report.
- Rich assignee search beyond `assignee=me`.
- Polling or reconciliation for PRs in unconnected repositories.

## Follow-up verification

- Model constraints and actor attribution for user, task, agent, system, and legacy rows.
- MCP client-name forwarding, generic MCP fallback, and direct-user attribution.
- Claim, silent takeover, same-actor idempotency, authorized release, and rejected release by another actor.
- Team scoping for claim, retrieve, filtering, and cross-project report IDs.
- PR attach, replace, release-with-PR, connected-state fetch, and unconnected unknown state.
- Derived work state across report status, ownership, and PR state combinations.
- `unclaimed`, `assignee=me`, and `has_implementation_pr` list filtering.
- Activity-log before/after entries and no-op suppression.
- Connected webhook scoping, one PR linked to several reports, merge resolution, and closed-unmerged suppression.
- Manual resolve/suppress PR-closing behavior.
- Replace the existing task-run-backed PR fixtures and assertions with assignment-backed equivalents.
- OpenAPI generation, generated MCP schema, tool-name lint, MCP typecheck, and focused backend tests.
