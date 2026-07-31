/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    EditReportRequestApi,
    EmitFindingRequestApi,
    EmitReportRequestApi,
    ForgetRequestApi,
    PatchedPullRequestReviewCommentUpdateApi,
    PatchedSignalReportArtefactLogUpdateApi,
    PatchedSignalReportContentUpdateApi,
    PatchedSignalScoutConfigUpdateApi,
    PatchedSignalSourceConfigApi,
    PauseUntilRequestApi,
    PullRequestReviewCommentCreateApi,
    PullRequestReviewCommentReactionCreateApi,
    RememberRequestApi,
    ScoutNoteCreateRequestApi,
    ScoutRunIdsBatchRequestApi,
    SignalReportArtefactLogCreateApi,
    SignalReportBulkStateRequestApi,
    SignalReportRefundRequestApi,
    SignalReportStateRequestApi,
    SignalScoutConfigCreateApi,
    SignalScoutCreateApi,
    SignalSourceConfigApi,
    SignalUserAutonomyConfigApi,
} from './api.zod.schemas'

/**
 * View and control signal processing pipeline state for a team.
 */
export const SignalsProcessingPauseUpdateBody = PauseUntilRequestApi

/**
 * Edit the human-facing title and/or summary (description) of a signal report, addressed by id. Both fields are optional — supply only the ones you want to change; at least one is required. Every other report field (status, weights, judgments) is managed by the signals pipeline and cannot be set here. Returns the full updated report.
 * @summary Edit a report's title or summary
 */
export const SignalsReportsPartialUpdateBody = PatchedSignalReportContentUpdateApi

/**
 * Post an inline review comment on the report's implementation pull request, attributed to the requesting user's own GitHub identity via their personal GitHub connection. Either replies to an existing thread (`in_reply_to`) or starts a new thread on a diff line (`path` + `line`).
 * @summary Post an inline review comment on a report's implementation PR
 */
export const SignalsReportPrReviewCommentsCreateBody = PullRequestReviewCommentCreateApi

/**
 * @summary Edit one of the requesting user's own review comments
 */
export const SignalsReportPrReviewCommentUpdateBody = PatchedPullRequestReviewCommentUpdateApi

/**
 * @summary React to a review comment as the requesting user
 */
export const SignalsReportPrReviewCommentReactionsCreateBody = PullRequestReviewCommentReactionCreateApi

/**
 * Refund the flat charge for this report's implementation PR and archive the report. Refunds auto-approve: the charge is either excluded from usage before it is ever reported to billing (refund on the same UTC day as the PR run) or returned as a Stripe customer-balance credit on the next invoice. A refunded PR does not count toward the free monthly PR allowance. One refund per report, ever — repeat calls return the existing refund with already_refunded=true. The report is archived as part of the refund (a resolved report stays resolved) and can't be restored afterwards.
 * @summary Refund a report's implementation PR
 */
export const SignalsReportsRefundCreateBody = SignalReportRefundRequestApi

/**
 * Transition a report to a new state. The model validates allowed transitions.
 *
 * The request body is validated by SignalReportStateRequestSerializer — only the
 * fields it declares (state, dismissal_reason, dismissal_note, snooze_for) are read,
 * and only snooze_for is ever forwarded to transition_to. Any other key is ignored,
 * so internal transition_to kwargs (reset_weight, error, ...) can't be injected.
 *
 * Body: {
 *     "state": "suppressed" | "potential" | "resolved",
 *     # Optional dismissal feedback (honored when state == "suppressed", "potential", or "resolved"):
 *     "dismissal_reason": "<canonical reason code, see SIGNAL_REPORT_DISMISSAL_REASON_CHOICES>",
 *     "dismissal_note": "free-form text",
 *     # Optional, only honored for state == "potential":
 *     "snooze_for": <number of additional signals before re-promotion>,
 * }
 */
export const SignalsReportsStateCreateBody = SignalReportStateRequestApi

/**
 * Append an artefact to a report (see artefact_type for the writable types). Everything is append-only: log entries (code reference, commit, task run, note) accumulate, while status types (safety / actionability / priority judgments, repo selection, suggested reviewers) are latest-wins — appending a new version supersedes the previous one as the report's canonical status. Content is validated against the type's schema.
 * @summary Append an artefact to a report
 */
export const SignalsReportArtefactsCreateBody = SignalReportArtefactLogCreateApi

/**
 * Replace the content of an existing artefact, addressed by id. The new content is validated against the artefact's type schema. Editing the latest row of a status type changes the report's canonical status (latest-wins); to re-assess while keeping history, append a new artefact instead. Attribution is creation-time only — edits don't reassign it.
 * @summary Replace an artefact's content
 */
export const SignalsReportArtefactsPartialUpdateBody = PatchedSignalReportArtefactLogUpdateApi

/**
 * Transition many reports to a new state in one call.
 *
 * Each id is processed independently: a report whose transition isn't allowed from its
 * current status is reported as `skipped` (a 409 on the single-report endpoint) and the
 * rest still go through. Returns one result per requested id (in request order, after
 * de-duplication) plus per-outcome counts. The whole call is 200 even on partial failure —
 * inspect `results` / the counts to see what happened.
 */
export const SignalsReportsBulkStateCreateBody = SignalReportBulkStateRequestApi

/**
 * Create a `signals-scout-*` skill and its runnable config atomically. The skill always receives the report-channel tools. The optional config controls schedule, enablement, dry-run posture, and typed destinations such as Slack. Repeating the same definition is safe and applies any supplied config fields; reusing its name for a different definition returns 409.
 * @summary Create a scout
 */
export const SignalsScoutCreateBody = SignalScoutCreateApi

/**
 * Register the config for a `signals-scout-*` skill immediately, without waiting for the coordinator to auto-register it. The same call can optionally set `run_interval_minutes`, a cron `run_cron_schedule`, `enabled`, `emit`, and output destinations. The skill must already exist on this project. Upsert: if a config already exists for the skill, the provided fields are applied to it.
 * @summary Create a scout config
 */
export const SignalsScoutConfigCreateBody = SignalScoutConfigCreateApi

/**
 * Tune one scout: change its schedule (rolling `run_interval_minutes`, or a cron `run_cron_schedule` that takes precedence when set), `enabled`, or `emit` (dry-run) posture, or output destinations. `skill_name` is fixed. Enabling records `enabled_by` and is activity-logged since it drives spend.
 * @summary Update a scout config
 */
export const SignalsScoutConfigUpdateBody = PatchedSignalScoutConfigUpdateApi

/**
 * Leave a steering note the scout fleet reads on its next runs. Address it to one scout via `skill_name` (`signals-scout-*`), or omit it for a general note every scout sees. Each call creates a new note (no upsert); delete retires one. Attributed to the authenticated user.
 * @summary Leave a note for the scouts
 */
export const SignalsScoutNotesCreateBody = ScoutNoteCreateRequestApi

/**
 * Rewrite a report's title/summary, append a note, and/or set its suggested reviewers. Can target ANY of the project's inbox reports, not just scout-authored ones — so the edit is attributed to this scout. Setting reviewers is how you rescue a report that surfaced routed to no one: it replaces the reviewer list and re-runs autostart, so a report missing a qualifying reviewer can open a draft PR. Title/summary edits are best-effort: the pipeline may later re-research them.
 * @summary Edit an existing report for a run
 */
export const SignalsScoutEditReportBody = EditReportRequestApi

/**
 * The second emit channel: author a complete `SignalReport` directly instead of emitting a weak signal. The report passes the safety judge, then surfaces at the status the scout's `actionability` call implies (or is suppressed). Backing `evidence` is written as bound signals so the report behaves like a pipeline report. NOT idempotent — a retry authors a second report; use `reports` to find a prior report and `edit-report` to update it instead.
 * @summary Author a full report for a run
 */
export const SignalsScoutEmitReportBody = EmitReportRequestApi

/**
 * Fire `emit_signal` with `source_product = signals_scout`. The `finding_id` is baked into the deterministic `Signal.source_id = run:<id>:finding:<id>` for traceability, but this is NOT idempotent — a second call with the same `finding_id` emits a second signal, so do not retry an emit that may have already succeeded.
 * @summary Emit a finding for a run
 */
export const SignalsScoutEmitSignalBody = EmitFindingRequestApi

/**
 * Batched form of the per-run emissions endpoint: return the findings every requested `SignalScoutRun` emitted, flattened newest-first, in a single request. Each row carries its `run_id`, so the caller can regroup by run. The findings UI uses this to load the whole recent window in one round-trip instead of one request per run. Strictly team-scoped — run ids belonging to another team contribute no rows (no per-run 404; one stale id never fails the batch).
 * @summary List emitted findings for many runs at once
 */
export const SignalsScoutRunsEmissionsBatchBody = ScoutRunIdsBatchRequestApi

/**
 * Batched form of the per-run emission-reports endpoint. For every finding the requested runs emitted, resolve the inbox `SignalReport` (if any) its signal grouped into — all in a single ClickHouse round-trip rather than one query per run, which is what made the findings page slow to open. `report` is null when a finding hasn't grouped yet, was de-duplicated, or its signal was deleted. Strictly team-scoped — run ids belonging to another team contribute no rows.
 * @summary List the inbox reports many runs' findings linked to
 */
export const SignalsScoutRunsEmissionReportsBatchBody = ScoutRunIdsBatchRequestApi

/**
 * Upsert a memory keyed on `(team, key)`. Re-using a key updates the existing entry in place.
 * @summary Remember a scratchpad entry
 */
export const SignalsScoutScratchpadRememberBody = RememberRequestApi

/**
 * Delete an entry by key. Returns `deleted=false` if no row matched.
 * @summary Forget a scratchpad entry by key
 */
export const SignalsScoutScratchpadForgetBody = ForgetRequestApi

export const SignalsSourceConfigsCreateBody = SignalSourceConfigApi

export const SignalsSourceConfigsUpdateBody = SignalSourceConfigApi

export const SignalsSourceConfigsPartialUpdateBody = PatchedSignalSourceConfigApi

/**
 * Per-user signal autonomy config (singleton keyed by user).
 *
 * GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
 * POST   /api/users/<id>/signal_autonomy/ → create or update
 * DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const UsersSignalAutonomyCreateBody = SignalUserAutonomyConfigApi
