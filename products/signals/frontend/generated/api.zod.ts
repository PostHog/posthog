/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * View and control signal processing pipeline state for a team.
 */
export const SignalsProcessingPauseUpdateBody = /* @__PURE__ */ zod.object({
    timestamp: zod.iso
        .datetime({ offset: true })
        .describe('Pause the grouping pipeline until this timestamp (ISO 8601).'),
})

/**
 * Edit the human-facing title and/or summary (description) of a signal report, addressed by id. Both fields are optional — supply only the ones you want to change; at least one is required. Every other report field (status, weights, judgments) is managed by the signals pipeline and cannot be set here. Returns the full updated report.
 * @summary Edit a report's title or summary
 */
export const signalsReportsPartialUpdateBodyTitleMax = 300

export const signalsReportsPartialUpdateBodySummaryMax = 10000

export const SignalsReportsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        title: zod
            .string()
            .min(1)
            .max(signalsReportsPartialUpdateBodyTitleMax)
            .optional()
            .describe('New human-facing title for the report. Omit to leave the title unchanged.'),
        summary: zod
            .string()
            .min(1)
            .max(signalsReportsPartialUpdateBodySummaryMax)
            .optional()
            .describe(
                "New summary (the report's description) explaining what the report is about. Omit to leave the summary unchanged."
            ),
    })
    .describe(
        'Editable human-facing fields on a signal report (PATCH).\n\nBoth fields are optional so a caller can change either independently, but at least one\nmust be supplied. Every other report field — status, weights, judgments — is owned by the\nsignals pipeline and is deliberately not writable here.'
    )

/**
 * Transition a report to a new state. The model validates allowed transitions.
 *
 * The request body is validated by SignalReportStateRequestSerializer — only the
 * fields it declares (state, dismissal_reason, dismissal_note, snooze_for) are read,
 * and only snooze_for is ever forwarded to transition_to. Any other key is ignored,
 * so internal transition_to kwargs (reset_weight, error, ...) can't be injected.
 *
 * Body: {
 *     "state": "suppressed" | "potential",
 *     # Optional dismissal feedback (honored when state == "suppressed" or "potential"):
 *     "dismissal_reason": "<canonical reason code, see SIGNAL_REPORT_DISMISSAL_REASON_CHOICES>",
 *     "dismissal_note": "free-form text",
 *     # Optional, only honored for state == "potential":
 *     "snooze_for": <number of additional signals before re-promotion>,
 * }
 */
export const signalsReportsStateCreateBodyDismissalNoteMax = 4000

export const signalsReportsStateCreateBodySnoozeForMax = 100000

export const SignalsReportsStateCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .enum(['suppressed', 'potential'])
        .describe('\* `suppressed` - suppressed\n\* `potential` - potential')
        .describe(
            "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, or 'potential' to snooze\/reopen it for later review.\n\n\* `suppressed` - suppressed\n\* `potential` - potential"
        ),
    dismissal_reason: zod
        .enum([
            'already_fixed',
            'report_unclear',
            'analysis_wrong',
            'wontfix_intentional',
            'wontfix_irrelevant',
            'other',
        ])
        .describe(
            "\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
        )
        .optional()
        .describe(
            "Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. 'already_fixed' is a snooze, not a dismissal: pair it with state='potential' (restore) so the report reappears if the issue recurs. Use 'other' together with a dismissal_note for anything that doesn't fit a code.\n\n\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
        ),
    dismissal_note: zod
        .string()
        .max(signalsReportsStateCreateBodyDismissalNoteMax)
        .optional()
        .describe('Optional free-form note explaining the dismissal. Capped at 4000 characters.'),
    snooze_for: zod
        .number()
        .min(1)
        .max(signalsReportsStateCreateBodySnoozeForMax)
        .optional()
        .describe(
            "Optional, only honored when state is 'potential'. Number of additional signals the report must accumulate before it is re-promoted into the pipeline — effectively snoozing it until then. Omit to let the report re-enter the pipeline on the next matching signal."
        ),
})

/**
 * Append an artefact to a report (see artefact_type for the writable types). Everything is append-only: log entries (code reference, commit, task run, note) accumulate, while status types (safety / actionability / priority judgments, repo selection, suggested reviewers) are latest-wins — appending a new version supersedes the previous one as the report's canonical status. Content is validated against the type's schema.
 * @summary Append an artefact to a report
 */
export const SignalsReportArtefactsCreateBody = /* @__PURE__ */ zod
    .object({
        artefact_type: zod
            .string()
            .describe(
                "The artefact type. One of: actionability_judgment, code_reference, commit, dismissal, note, priority_judgment, repo_selection, safety_judgment, signal_finding, suggested_reviewers, task_run. Log types accumulate; status types (safety_judgment, actionability_judgment, priority_judgment, repo_selection, suggested_reviewers) are latest-wins — appending a new version supersedes the previous one as the report's canonical status."
            ),
        content: zod
            .unknown()
            .describe(
                'The artefact payload as a JSON object or array; shape depends on artefact_type and is validated against its schema.'
            ),
    })
    .describe(
        "Body for appending an artefact to a report.\n\nEverything is append-only: log artefacts accumulate, status artefacts supersede the previous\nversion (latest-wins). The `content` shape depends on `artefact_type` and is validated\nagainst the type's schema (see `products\/signals\/backend\/artefact_schemas.py`)."
    )

/**
 * Replace the content of an existing artefact, addressed by id. The new content is validated against the artefact's type schema. Editing the latest row of a status type changes the report's canonical status (latest-wins); to re-assess while keeping history, append a new artefact instead. Attribution is creation-time only — edits don't reassign it.
 * @summary Replace an artefact's content
 */
export const SignalsReportArtefactsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        content: zod
            .unknown()
            .optional()
            .describe("The new artefact payload as a JSON object or array, matching the artefact type's schema."),
    })
    .describe(
        "Body for replacing the content of an existing artefact (addressed by id).\n\nPer-type schema validation happens in the view, which knows the artefact's type."
    )

/**
 * Transition many reports to a new state in one call.
 *
 * Each id is processed independently: a report whose transition isn't allowed from its
 * current status is reported as `skipped` (a 409 on the single-report endpoint) and the
 * rest still go through. Returns one result per requested id (in request order, after
 * de-duplication) plus per-outcome counts. The whole call is 200 even on partial failure —
 * inspect `results` / the counts to see what happened.
 */
export const signalsReportsBulkStateCreateBodyDismissalNoteMax = 4000

export const signalsReportsBulkStateCreateBodySnoozeForMax = 100000

export const signalsReportsBulkStateCreateBodyIdsMax = 100

export const SignalsReportsBulkStateCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .enum(['suppressed', 'potential'])
        .describe('\* `suppressed` - suppressed\n\* `potential` - potential')
        .describe(
            "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, or 'potential' to snooze\/reopen it for later review.\n\n\* `suppressed` - suppressed\n\* `potential` - potential"
        ),
    dismissal_reason: zod
        .enum([
            'already_fixed',
            'report_unclear',
            'analysis_wrong',
            'wontfix_intentional',
            'wontfix_irrelevant',
            'other',
        ])
        .describe(
            "\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
        )
        .optional()
        .describe(
            "Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. 'already_fixed' is a snooze, not a dismissal: pair it with state='potential' (restore) so the report reappears if the issue recurs. Use 'other' together with a dismissal_note for anything that doesn't fit a code.\n\n\* `already_fixed` - Already fixed\n\* `report_unclear` - Report is unclear to me\n\* `analysis_wrong` - Agent's analysis is wrong\n\* `wontfix_intentional` - Won't fix - intentional behavior\n\* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n\* `other` - Something else…"
        ),
    dismissal_note: zod
        .string()
        .max(signalsReportsBulkStateCreateBodyDismissalNoteMax)
        .optional()
        .describe('Optional free-form note explaining the dismissal. Capped at 4000 characters.'),
    snooze_for: zod
        .number()
        .min(1)
        .max(signalsReportsBulkStateCreateBodySnoozeForMax)
        .optional()
        .describe(
            "Optional, only honored when state is 'potential'. Number of additional signals the report must accumulate before it is re-promoted into the pipeline — effectively snoozing it until then. Omit to let the report re-enter the pipeline on the next matching signal."
        ),
    ids: zod
        .array(zod.uuid())
        .max(signalsReportsBulkStateCreateBodyIdsMax)
        .describe(
            'Report ids to transition to `state` in one call (1–100). Duplicates are de-duplicated; each id is processed independently so one disallowed transition does not block the rest. `dismissal_reason`, `dismissal_note` and `snooze_for` apply to every id.'
        ),
})

/**
 * Register the config for a `signals-scout-*` skill immediately, without waiting for the coordinator to auto-register it — optionally setting `run_interval_minutes`, `enabled`, and `emit` in the same call. The skill must already exist on this project. Upsert: if a config already exists for the skill, the provided fields are applied to it.
 * @summary Create a scout config
 */
export const signalsScoutConfigCreateBodySkillNameMax = 200

export const signalsScoutConfigCreateBodyRunIntervalMinutesMin = 30
export const signalsScoutConfigCreateBodyRunIntervalMinutesMax = 43200

export const SignalsScoutConfigCreateBody = /* @__PURE__ */ zod
    .object({
        skill_name: zod
            .string()
            .max(signalsScoutConfigCreateBodySkillNameMax)
            .describe(
                'The `signals-scout-\*` skill to register a config for. The skill must already exist on this project — author it via the skills store first.'
            ),
        enabled: zod.boolean().optional().describe('Whether this scout runs on its schedule. Defaults to true.'),
        emit: zod
            .boolean()
            .optional()
            .describe(
                'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. Defaults to true.'
            ),
        run_interval_minutes: zod
            .number()
            .min(signalsScoutConfigCreateBodyRunIntervalMinutesMin)
            .max(signalsScoutConfigCreateBodyRunIntervalMinutesMax)
            .optional()
            .describe('Minutes between runs (30–43200). Defaults to 1440 (every 24 hours).'),
    })
    .describe(
        'Request body for registering a scout config without waiting for the coordinator tick.\n\nUpsert keyed on `skill_name`: if the coordinator (or a concurrent caller) already\nregistered the row, the provided tunables are applied to it instead.'
    )

/**
 * Tune one scout: change its schedule (`run_interval_minutes`), `enabled`, or `emit` (dry-run) posture. `skill_name` is fixed. Enabling records `enabled_by` and is activity-logged since it drives spend.
 * @summary Update a scout config
 */
export const signalsScoutConfigUpdateBodyRunIntervalMinutesMin = 30
export const signalsScoutConfigUpdateBodyRunIntervalMinutesMax = 43200

export const SignalsScoutConfigUpdateBody = /* @__PURE__ */ zod
    .object({
        enabled: zod
            .boolean()
            .optional()
            .describe('Whether this scout runs on its schedule. Disabled scouts are skipped by the coordinator.'),
        emit: zod
            .boolean()
            .optional()
            .describe(
                'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing.'
            ),
        run_interval_minutes: zod
            .number()
            .min(signalsScoutConfigUpdateBodyRunIntervalMinutesMin)
            .max(signalsScoutConfigUpdateBodyRunIntervalMinutesMax)
            .optional()
            .describe(
                'Minutes between runs (30–43200). The scout runs once this interval has elapsed since its last run.'
            ),
    })
    .describe(
        'Per-(team, skill) scout config: schedule, enablement, and emit posture.\n\nOne row per `signals-scout-\*` skill on the team. The coordinator auto-creates a row\nwhen it discovers a scout skill; this serializer lets agents tune the row.'
    )

/**
 * Rewrite a report's title/summary, append a note, and/or set its suggested reviewers. Can target ANY of the project's inbox reports, not just scout-authored ones — so the edit is attributed to this scout. Setting reviewers is how you rescue a report that surfaced routed to no one: it replaces the reviewer list and re-runs autostart, so a report missing a qualifying reviewer can open a draft PR. Title/summary edits are best-effort: the pipeline may later re-research them.
 * @summary Edit an existing report for a run
 */
export const signalsScoutEditReportBodyTitleMax = 300

export const signalsScoutEditReportBodySuggestedReviewersItemGithubLoginMax = 200

export const signalsScoutEditReportBodySuggestedReviewersMax = 10

export const SignalsScoutEditReportBody = /* @__PURE__ */ zod
    .object({
        report_id: zod.string().describe('Id of the report to edit (must belong to this project).'),
        title: zod
            .string()
            .max(signalsScoutEditReportBodyTitleMax)
            .nullish()
            .describe(
                'Optional new title. Conventional-commit style (`type(scope): description`) renders with type\/scope styling. The pipeline may later re-research and overwrite it.'
            ),
        summary: zod
            .string()
            .nullish()
            .describe(
                'Optional new summary. Markdown is supported (headings, lists, code, links; images are not rendered); lead with one plain declarative sentence — it becomes the inbox card headline. The pipeline may later re-research and overwrite it.'
            ),
        append_note: zod
            .string()
            .nullish()
            .describe("Optional free-form note to append to the report's work log (attributed to this scout)."),
        suggested_reviewers: zod
            .array(
                zod
                    .object({
                        github_login: zod
                            .string()
                            .max(signalsScoutEditReportBodySuggestedReviewersItemGithubLoginMax)
                            .optional()
                            .describe(
                                'GitHub login (case-insensitive, stored lowercased) — e.g. `octocat`, no `@`, no display name. Resolve one via `signals-scout-members-list` (each member row carries a resolved `github_login`) or git history when you only have a name.'
                            ),
                        user_uuid: zod
                            .uuid()
                            .optional()
                            .describe(
                                "PostHog user UUID (e.g. from `signals-scout-members-list`, or an entity's `created_by`). Resolved server-side to the member's linked GitHub login — use this when you know the PostHog user but not their GitHub handle. Must be a concrete UUID; the `@me` alias is not valid here."
                            ),
                    })
                    .describe(
                        "One suggested reviewer — identified by `github_login`, `user_uuid`, or both.\n\nThe server canonicalizes each entry to a lowercased GitHub login: a `user_uuid` is resolved to the\norg member's linked GitHub login (and wins over a supplied `github_login` when both are given). A\n`user_uuid` that isn't an org member of this team with a linked GitHub identity is rejected — so a\nreviewer is never silently dropped."
                    )
            )
            .max(signalsScoutEditReportBodySuggestedReviewersMax)
            .optional()
            .describe(
                'Optional reviewers to set on the report (each a `github_login` and\/or `user_uuid`), replacing any existing list. Use this to route a report that surfaced with no reviewer — it re-runs autostart, so a report that was missing a qualifying reviewer can now open a draft PR. An empty list is a no-op (existing reviewers are left untouched, never cleared).'
            ),
    })
    .describe(
        "Request body for `edit-report`. Can target ANY of the team's inbox reports, not just scout-authored ones."
    )

/**
 * The second emit channel: author a complete `SignalReport` directly instead of emitting a weak signal. The report passes the safety judge, then surfaces at the status the scout's `actionability` call implies (or is suppressed). Backing `evidence` is written as bound signals so the report behaves like a pipeline report. NOT idempotent — a retry authors a second report; use `reports` to find a prior report and `edit-report` to update it instead.
 * @summary Author a full report for a run
 */
export const signalsScoutEmitReportBodyTitleMax = 300

export const signalsScoutEmitReportBodyEvidenceItemWeightMin = 0

export const signalsScoutEmitReportBodyAlreadyAddressedDefault = false
export const signalsScoutEmitReportBodySuggestedReviewersItemGithubLoginMax = 200

export const signalsScoutEmitReportBodySuggestedReviewersMax = 10

export const SignalsScoutEmitReportBody = /* @__PURE__ */ zod
    .object({
        title: zod
            .string()
            .max(signalsScoutEmitReportBodyTitleMax)
            .describe(
                'One-line report title the inbox shows. Conventional-commit style (`type(scope): description`, e.g. `fix(insights): missing series color`) renders with type\/scope styling.'
            ),
        summary: zod
            .string()
            .describe(
                'The report body the inbox shows. Markdown is supported (headings, lists, code, links; images are not rendered). Lead with one plain declarative sentence — the inbox card uses your first line verbatim as the headline (~140 chars, emphasis stripped), then renders the full markdown in the detail view.'
            ),
        evidence: zod
            .array(
                zod
                    .object({
                        description: zod
                            .string()
                            .describe(
                                'Prose for this observation. Embedded and rendered to the safety\/research surfaces.'
                            ),
                        source_id: zod
                            .string()
                            .describe(
                                'Stable id for this observation within the report (lets a later edit address it).'
                            ),
                        weight: zod
                            .number()
                            .min(signalsScoutEmitReportBodyEvidenceItemWeightMin)
                            .optional()
                            .describe('Optional per-signal weight (defaults to 1.0). Scouts rarely need to set this.'),
                    })
                    .describe('One observation backing an authored report — becomes a bound signal row on the report.')
            )
            .min(1)
            .describe('The observations backing the report — each becomes a bound signal. At least one.'),
        actionability_explanation: zod
            .string()
            .describe('2-3 sentence evidence-grounded justification for the actionability call below.'),
        actionability: zod
            .enum(['immediately_actionable', 'requires_human_input', 'not_actionable'])
            .describe(
                '\* `immediately_actionable` - immediately_actionable\n\* `requires_human_input` - requires_human_input\n\* `not_actionable` - not_actionable'
            )
            .describe(
                "The scout's actionability call: `immediately_actionable` -> the report surfaces READY; `requires_human_input` -> PENDING_INPUT; `not_actionable` -> suppressed. A safety-judge failure suppresses the report regardless.\n\n\* `immediately_actionable` - immediately_actionable\n\* `requires_human_input` - requires_human_input\n\* `not_actionable` - not_actionable"
            ),
        already_addressed: zod
            .boolean()
            .default(signalsScoutEmitReportBodyAlreadyAddressedDefault)
            .describe('Whether the issue already appears fixed in recent changes (tracked separately).'),
        repository: zod
            .string()
            .nullish()
            .describe(
                "Optional repo for autostart (opening a draft PR): `owner\/repo` targets that repo, the `NO_REPO` sentinel opts out (report lands without a PR), and omitting it triggers free-form selection across the team's repos — the slow path on a many-repo team, so pass `owner\/repo` when you know it."
            ),
        priority: zod
            .union([
                zod
                    .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                    .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'),
                zod.null(),
            ])
            .optional()
            .describe(
                'Optional priority (`P0`-`P4`). Required for autostart; pair with `priority_explanation`.\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'
            ),
        priority_explanation: zod
            .string()
            .nullish()
            .describe('2-3 sentence justification for `priority`. Required when `priority` is set.'),
        suggested_reviewers: zod
            .array(
                zod
                    .object({
                        github_login: zod
                            .string()
                            .max(signalsScoutEmitReportBodySuggestedReviewersItemGithubLoginMax)
                            .optional()
                            .describe(
                                'GitHub login (case-insensitive, stored lowercased) — e.g. `octocat`, no `@`, no display name. Resolve one via `signals-scout-members-list` (each member row carries a resolved `github_login`) or git history when you only have a name.'
                            ),
                        user_uuid: zod
                            .uuid()
                            .optional()
                            .describe(
                                "PostHog user UUID (e.g. from `signals-scout-members-list`, or an entity's `created_by`). Resolved server-side to the member's linked GitHub login — use this when you know the PostHog user but not their GitHub handle. Must be a concrete UUID; the `@me` alias is not valid here."
                            ),
                    })
                    .describe(
                        "One suggested reviewer — identified by `github_login`, `user_uuid`, or both.\n\nThe server canonicalizes each entry to a lowercased GitHub login: a `user_uuid` is resolved to the\norg member's linked GitHub login (and wins over a supplied `github_login` when both are given). A\n`user_uuid` that isn't an org member of this team with a linked GitHub identity is rejected — so a\nreviewer is never silently dropped."
                    )
            )
            .max(signalsScoutEmitReportBodySuggestedReviewersMax)
            .optional()
            .describe(
                "Optional reviewers to route the report to (each a `github_login` and\/or `user_uuid`). This is the primary way a report reaches a human — the inbox floats a reviewer's own reports to the top of their inbox even when no PR is involved — so set it whenever you can name a plausible owner. It also gates autostart: a PR opens only if at least one reviewer clears their autonomy threshold."
            ),
    })
    .describe('Request body for `emit-report`. Run attribution is taken from the URL path.')

/**
 * Fire `emit_signal` with `source_product = signals_scout`. The `finding_id` is baked into the deterministic `Signal.source_id = run:<id>:finding:<id>` for traceability, but this is NOT idempotent — a second call with the same `finding_id` emits a second signal, so do not retry an emit that may have already succeeded.
 * @summary Emit a finding for a run
 */
export const signalsScoutEmitSignalBodyDescriptionMax = 50000

export const signalsScoutEmitSignalBodyConfidenceMin = 0
export const signalsScoutEmitSignalBodyConfidenceMax = 1

export const signalsScoutEmitSignalBodyEvidenceMax = 20

export const signalsScoutEmitSignalBodyTagsItemMax = 50

export const signalsScoutEmitSignalBodyTagsMax = 10

export const signalsScoutEmitSignalBodyFindingIdMax = 100

export const SignalsScoutEmitSignalBody = /* @__PURE__ */ zod
    .object({
        description: zod
            .string()
            .max(signalsScoutEmitSignalBodyDescriptionMax)
            .describe("Canonical evidence-bundle prose. Becomes the signal's `description`."),
        confidence: zod
            .number()
            .min(signalsScoutEmitSignalBodyConfidenceMin)
            .max(signalsScoutEmitSignalBodyConfidenceMax)
            .describe("Agent's confidence the finding is real in [0, 1]. Persisted in `extra`."),
        evidence: zod
            .array(
                zod
                    .object({
                        source_product: zod
                            .string()
                            .describe(
                                'Source the citation came from (`error_tracking`, `session_replay`, `logs`, ...).'
                            ),
                        summary: zod
                            .string()
                            .describe('One-sentence prose about why this evidence supports the finding.'),
                        entity_id: zod
                            .string()
                            .nullish()
                            .describe('Optional ID of the cited entity (issue id, recording id, log query id).'),
                    })
                    .describe('One citation attached to a finding. Mirrors `SignalsScoutEvidenceEntry`.')
            )
            .max(signalsScoutEmitSignalBodyEvidenceMax)
            .describe('Citations supporting the finding. Capped at 20 entries.'),
        hypothesis: zod.string().nullish().describe('Optional one-line hypothesis the finding tests.'),
        severity: zod
            .union([
                zod
                    .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                    .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'),
                zod.null(),
            ])
            .optional()
            .describe(
                'Optional severity tag — one of P0, P1, P2, P3, P4. Informational only.\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'
            ),
        dedupe_keys: zod
            .array(zod.string())
            .optional()
            .describe('Optional keys for downstream dedupe (e.g. `error_tracking_issue:<id>`).'),
        tags: zod
            .array(zod.string().max(signalsScoutEmitSignalBodyTagsItemMax))
            .max(signalsScoutEmitSignalBodyTagsMax)
            .optional()
            .describe(
                "Optional category tags as lowercase kebab-case slugs (e.g. `cost-spike`, `silent-failure`), max 10. Reuse the vocabulary in your `tags:<domain>:taxonomy` scratchpad entry when a tag fits; coin a new slug when a genuinely new category emerges. Near-miss formats are normalized to slugs; persisted in the signal's `extra.tags` and on the emission row."
            ),
        time_range: zod
            .union([
                zod.object({
                    date_from: zod.string().describe("ISO-8601 inclusive lower bound for the finding's window."),
                    date_to: zod.string().describe("ISO-8601 inclusive upper bound for the finding's window."),
                }),
                zod.null(),
            ])
            .optional()
            .describe('Optional time window the finding refers to.'),
        mcp_trace_id: zod.string().nullish().describe('Optional MCP trace id for cross-system debugging.'),
        finding_id: zod
            .string()
            .max(signalsScoutEmitSignalBodyFindingIdMax)
            .nullish()
            .describe(
                "Stable id for this finding, baked into the signal's source_id for traceability. NOT a dedupe key — re-emitting the same id creates another signal."
            ),
    })
    .describe('Request body for `emit-finding`. Run attribution is taken from the URL path.')

/**
 * Batched form of the per-run emissions endpoint: return the findings every requested `SignalScoutRun` emitted, flattened newest-first, in a single request. Each row carries its `run_id`, so the caller can regroup by run. The findings UI uses this to load the whole recent window in one round-trip instead of one request per run. Strictly team-scoped — run ids belonging to another team contribute no rows (no per-run 404; one stale id never fails the batch).
 * @summary List emitted findings for many runs at once
 */
export const signalsScoutRunsEmissionsBatchBodyRunIdsMax = 200

export const SignalsScoutRunsEmissionsBatchBody = /* @__PURE__ */ zod
    .object({
        run_ids: zod
            .array(zod.uuid())
            .max(signalsScoutRunsEmissionsBatchBodyRunIdsMax)
            .describe(
                'UUIDs of the `SignalScoutRun` rows to resolve in one batch. Run ids belonging to another team are silently ignored (they contribute no rows) rather than failing the whole request. Capped at 200 ids per call.'
            ),
    })
    .describe(
        "Request body for the batched emissions \/ emission-reports lookups: the set of run UUIDs to\nresolve in one call. Collapses the findings UI's old per-run fan-out (one request — and for the\nreports lookup, one ClickHouse round-trip — per emitted run) into a single request."
    )

/**
 * Batched form of the per-run emission-reports endpoint. For every finding the requested runs emitted, resolve the inbox `SignalReport` (if any) its signal grouped into — all in a single ClickHouse round-trip rather than one query per run, which is what made the findings page slow to open. `report` is null when a finding hasn't grouped yet, was de-duplicated, or its signal was deleted. Strictly team-scoped — run ids belonging to another team contribute no rows.
 * @summary List the inbox reports many runs' findings linked to
 */
export const signalsScoutRunsEmissionReportsBatchBodyRunIdsMax = 200

export const SignalsScoutRunsEmissionReportsBatchBody = /* @__PURE__ */ zod
    .object({
        run_ids: zod
            .array(zod.uuid())
            .max(signalsScoutRunsEmissionReportsBatchBodyRunIdsMax)
            .describe(
                'UUIDs of the `SignalScoutRun` rows to resolve in one batch. Run ids belonging to another team are silently ignored (they contribute no rows) rather than failing the whole request. Capped at 200 ids per call.'
            ),
    })
    .describe(
        "Request body for the batched emissions \/ emission-reports lookups: the set of run UUIDs to\nresolve in one call. Collapses the findings UI's old per-run fan-out (one request — and for the\nreports lookup, one ClickHouse round-trip — per emitted run) into a single request."
    )

/**
 * Upsert a memory keyed on `(team, key)`. Re-using a key updates the existing entry in place.
 * @summary Remember a scratchpad entry
 */
export const signalsScoutScratchpadRememberBodyKeyMax = 300

export const signalsScoutScratchpadRememberBodyContentMax = 50000

export const SignalsScoutScratchpadRememberBody = /* @__PURE__ */ zod
    .object({
        key: zod
            .string()
            .max(signalsScoutScratchpadRememberBodyKeyMax)
            .describe(
                "Agent-chosen semantic key, unique per team; re-using a key overwrites the entry in place. Key off the \*stable identity\* of what you're tracking — never embed a date, timestamp, or run id (that mints a new row every run and breaks dedupe). For run state\/cursors, use one fixed key and keep the timestamp in `content`."
            ),
        content: zod
            .string()
            .max(signalsScoutScratchpadRememberBodyContentMax)
            .describe('Prose to write. Read verbatim into future prompts.'),
        run_id: zod
            .uuid()
            .nullish()
            .describe(
                "Run that authored this memory; persisted as `created_by_run_id` for lineage. Best-effort — a `run_id` that isn't a run on this project is dropped (lineage left null), not rejected, so the memory write is never lost."
            ),
    })
    .describe('Request body for `remember`.')

/**
 * Delete an entry by key. Returns `deleted=false` if no row matched.
 * @summary Forget a scratchpad entry by key
 */
export const signalsScoutScratchpadForgetBodyKeyMax = 300

export const SignalsScoutScratchpadForgetBody = /* @__PURE__ */ zod
    .object({
        key: zod.string().max(signalsScoutScratchpadForgetBodyKeyMax).describe('Memory key to delete.'),
    })
    .describe('Request body for `forget`.')

export const SignalsSourceConfigsCreateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum([
            'session_replay',
            'llm_analytics',
            'github',
            'linear',
            'zendesk',
            'conversations',
            'error_tracking',
            'pganalyze',
            'signals_scout',
            'logs',
            'health_checks',
            'endpoints',
            'replay_vision',
            'engineering_analytics',
        ])
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints\n\* `replay_vision` - Replay Vision\n\* `engineering_analytics` - Engineering analytics'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation',
            'evaluation_report',
            'issue',
            'ticket',
            'issue_created',
            'issue_reopened',
            'issue_spiking',
            'cross_source_issue',
            'alert_state_change',
            'health_issue',
            'endpoint_execution_failed',
            'endpoint_breakdown_limit_exceeded',
            'scanner_finding',
            'ci_flaky_check',
            'ci_broken_master',
            'ci_duration_regression',
        ])
        .describe(
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `evaluation_report` - Evaluation report\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n\* `scanner_finding` - Scanner finding\n\* `ci_flaky_check` - CI flaky check\n\* `ci_broken_master` - CI broken master\n\* `ci_duration_regression` - CI duration regression'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

export const SignalsSourceConfigsUpdateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum([
            'session_replay',
            'llm_analytics',
            'github',
            'linear',
            'zendesk',
            'conversations',
            'error_tracking',
            'pganalyze',
            'signals_scout',
            'logs',
            'health_checks',
            'endpoints',
            'replay_vision',
            'engineering_analytics',
        ])
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints\n\* `replay_vision` - Replay Vision\n\* `engineering_analytics` - Engineering analytics'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation',
            'evaluation_report',
            'issue',
            'ticket',
            'issue_created',
            'issue_reopened',
            'issue_spiking',
            'cross_source_issue',
            'alert_state_change',
            'health_issue',
            'endpoint_execution_failed',
            'endpoint_breakdown_limit_exceeded',
            'scanner_finding',
            'ci_flaky_check',
            'ci_broken_master',
            'ci_duration_regression',
        ])
        .describe(
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `evaluation_report` - Evaluation report\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n\* `scanner_finding` - Scanner finding\n\* `ci_flaky_check` - CI flaky check\n\* `ci_broken_master` - CI broken master\n\* `ci_duration_regression` - CI duration regression'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

export const SignalsSourceConfigsPartialUpdateBody = /* @__PURE__ */ zod.object({
    source_product: zod
        .enum([
            'session_replay',
            'llm_analytics',
            'github',
            'linear',
            'zendesk',
            'conversations',
            'error_tracking',
            'pganalyze',
            'signals_scout',
            'logs',
            'health_checks',
            'endpoints',
            'replay_vision',
            'engineering_analytics',
        ])
        .optional()
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints\n\* `replay_vision` - Replay Vision\n\* `engineering_analytics` - Engineering analytics'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation',
            'evaluation_report',
            'issue',
            'ticket',
            'issue_created',
            'issue_reopened',
            'issue_spiking',
            'cross_source_issue',
            'alert_state_change',
            'health_issue',
            'endpoint_execution_failed',
            'endpoint_breakdown_limit_exceeded',
            'scanner_finding',
            'ci_flaky_check',
            'ci_broken_master',
            'ci_duration_regression',
        ])
        .optional()
        .describe(
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `evaluation_report` - Evaluation report\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n\* `scanner_finding` - Scanner finding\n\* `ci_flaky_check` - CI flaky check\n\* `ci_broken_master` - CI broken master\n\* `ci_duration_regression` - CI duration regression'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

/**
 * Per-user signal autonomy config (singleton keyed by user).
 *
 * GET    /api/users/<id>/signal_autonomy/ → current config (or 404)
 * POST   /api/users/<id>/signal_autonomy/ → create or update
 * DELETE /api/users/<id>/signal_autonomy/ → remove (opt out)
 */
export const usersSignalAutonomyCreateBodySlackNotificationChannelMax = 255

export const UsersSignalAutonomyCreateBody = /* @__PURE__ */ zod.object({
    autostart_priority: zod
        .union([
            zod
                .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional(),
    slack_notification_channel: zod
        .string()
        .max(usersSignalAutonomyCreateBodySlackNotificationChannelMax)
        .nullish()
        .describe(
            'Slack channel target in the same `channel_id|#channel-name` shape PostHog uses elsewhere (only the channel id is required). Null disables Slack notifications.'
        ),
    slack_notification_min_priority: zod
        .union([
            zod
                .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                .describe('\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'),
            zod.enum(['']),
            zod.null(),
        ])
        .optional()
        .describe(
            'Minimum report priority that triggers a Slack notification. P0 is highest. Null means notify on every priority (and reports without a priority judgment).\n\n\* `P0` - P0\n\* `P1` - P1\n\* `P2` - P2\n\* `P3` - P3\n\* `P4` - P4'
        ),
})
