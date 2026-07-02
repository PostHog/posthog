/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 34 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const SignalsReportsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SignalsReportsListQueryParams = /* @__PURE__ */ zod.object({
    has_implementation_pr: zod
        .boolean()
        .optional()
        .describe(
            "Filter reports by whether a shipped implementation pull request exists. 'true' keeps only reports with a PR; 'false' keeps only those without. Pair with limit=1 to count PR reports cheaply."
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    ordering: zod
        .string()
        .optional()
        .describe(
            "Comma-separated ordering clauses. Each clause is a field name optionally prefixed with '-' for descending. Allowed fields: status, is_suggested_reviewer, signal_count, total_weight, priority, created_at, updated_at, id. Defaults to '-is_suggested_reviewer,status,-updated_at'."
        ),
    priority: zod
        .string()
        .optional()
        .describe(
            'Comma-separated list of priorities to include. Valid values: P0, P1, P2, P3, P4. Reports without a priority assignment are excluded when this filter is set.'
        ),
    search: zod.string().optional().describe('Case-insensitive substring match against report title and summary.'),
    source_product: zod
        .string()
        .optional()
        .describe(
            'Comma-separated list of source products to include. Reports are kept if at least one of their contributing signals comes from one of these products (e.g. error_tracking, session_replay).'
        ),
    status: zod
        .string()
        .optional()
        .describe(
            'Comma-separated list of statuses to include. Valid values: potential, candidate, in_progress, pending_input, ready, resolved, failed, suppressed. Defaults to all statuses except suppressed.'
        ),
    suggested_reviewers: zod
        .string()
        .optional()
        .describe(
            'Comma-separated list of PostHog user UUIDs. Reports are kept if their suggested reviewers include any of the given users.'
        ),
    task_id: zod
        .string()
        .optional()
        .describe("Only reports associated with this task (via the report's task associations)."),
})

export const SignalsReportsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Edit the human-facing title and/or summary (description) of a signal report, addressed by id. Both fields are optional — supply only the ones you want to change; at least one is required. Every other report field (status, weights, judgments) is managed by the signals pipeline and cannot be set here. Returns the full updated report.
 * @summary Edit a report's title or summary
 */
export const SignalsReportsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
export const SignalsReportsStateCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsReportsStateCreateBodyDismissalNoteMax = 4000

export const signalsReportsStateCreateBodySnoozeForMax = 100000

export const SignalsReportsStateCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .enum(['suppressed', 'potential'])
        .describe('* `suppressed` - suppressed\n* `potential` - potential')
        .describe(
            "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, or 'potential' to snooze/reopen it for later review.\n\n* `suppressed` - suppressed\n* `potential` - potential"
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
            "* `already_fixed` - Already fixed\n* `report_unclear` - Report is unclear to me\n* `analysis_wrong` - Agent's analysis is wrong\n* `wontfix_intentional` - Won't fix - intentional behavior\n* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n* `other` - Something else…"
        )
        .optional()
        .describe(
            "Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. 'already_fixed' is a snooze, not a dismissal: pair it with state='potential' (restore) so the report reappears if the issue recurs. Use 'other' together with a dismissal_note for anything that doesn't fit a code.\n\n* `already_fixed` - Already fixed\n* `report_unclear` - Report is unclear to me\n* `analysis_wrong` - Agent's analysis is wrong\n* `wontfix_intentional` - Won't fix - intentional behavior\n* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n* `other` - Something else…"
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
 * List every artefact on a report — the full work log: signal findings (the evidence behind the report), status judgments (safety / actionability / priority, repo selection, suggested reviewers — the newest row of each status type is canonical), and log entries (code references, commits, task runs, notes). `suggested_reviewers` content is enriched with PostHog user info at read time.
 * @summary List a report's artefacts
 */
export const SignalsReportArtefactsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    report_id: zod.string(),
})

export const SignalsReportArtefactsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Append an artefact to a report (see artefact_type for the writable types). Everything is append-only: log entries (code reference, commit, task run, note) accumulate, while status types (safety / actionability / priority judgments, repo selection, suggested reviewers) are latest-wins — appending a new version supersedes the previous one as the report's canonical status. Content is validated against the type's schema.
 * @summary Append an artefact to a report
 */
export const SignalsReportArtefactsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    report_id: zod.string(),
})

export const SignalsReportArtefactsCreateHeader = /* @__PURE__ */ zod.object({
    'X-PostHog-Task-Id': zod
        .string()
        .optional()
        .describe(
            'Task to attribute the artefact to (must belong to this project). Set automatically for sandbox agents; when absent the artefact is attributed to the requesting user.'
        ),
})

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
        "Body for appending an artefact to a report.\n\nEverything is append-only: log artefacts accumulate, status artefacts supersede the previous\nversion (latest-wins). The `content` shape depends on `artefact_type` and is validated\nagainst the type's schema (see `products/signals/backend/artefact_schemas.py`)."
    )

/**
 * Get one artefact by id, content parsed (and reviewers enriched) the same way as the list.
 * @summary Get a single artefact
 */
export const SignalsReportArtefactsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal report artefact.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    report_id: zod.string(),
})

/**
 * Replace the content of an existing artefact, addressed by id. The new content is validated against the artefact's type schema. Editing the latest row of a status type changes the report's canonical status (latest-wins); to re-assess while keeping history, append a new artefact instead. Attribution is creation-time only — edits don't reassign it.
 * @summary Replace an artefact's content
 */
export const SignalsReportArtefactsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal report artefact.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    report_id: zod.string(),
})

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
 * Delete an artefact, addressed by id. Deleting the latest row of a status type reverts the report's canonical status to the previous version (latest-wins over what remains).
 * @summary Delete an artefact
 */
export const SignalsReportArtefactsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal report artefact.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    report_id: zod.string(),
})

/**
 * Transition many reports to a new state in one call.
 *
 * Each id is processed independently: a report whose transition isn't allowed from its
 * current status is reported as `skipped` (a 409 on the single-report endpoint) and the
 * rest still go through. Returns one result per requested id (in request order, after
 * de-duplication) plus per-outcome counts. The whole call is 200 even on partial failure —
 * inspect `results` / the counts to see what happened.
 */
export const SignalsReportsBulkStateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsReportsBulkStateCreateBodyDismissalNoteMax = 4000

export const signalsReportsBulkStateCreateBodySnoozeForMax = 100000

export const signalsReportsBulkStateCreateBodyIdsMax = 100

export const SignalsReportsBulkStateCreateBody = /* @__PURE__ */ zod.object({
    state: zod
        .enum(['suppressed', 'potential'])
        .describe('* `suppressed` - suppressed\n* `potential` - potential')
        .describe(
            "Target state for the report. Use 'suppressed' to dismiss the report from the inbox, or 'potential' to snooze/reopen it for later review.\n\n* `suppressed` - suppressed\n* `potential` - potential"
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
            "* `already_fixed` - Already fixed\n* `report_unclear` - Report is unclear to me\n* `analysis_wrong` - Agent's analysis is wrong\n* `wontfix_intentional` - Won't fix - intentional behavior\n* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n* `other` - Something else…"
        )
        .optional()
        .describe(
            "Optional canonical reason code for the dismissal. Must be one of: already_fixed, report_unclear, analysis_wrong, wontfix_intentional, wontfix_irrelevant, other — these match the inbox UI so the rationale renders as a labelled chip rather than a raw code. 'already_fixed' is a snooze, not a dismissal: pair it with state='potential' (restore) so the report reappears if the issue recurs. Use 'other' together with a dismissal_note for anything that doesn't fit a code.\n\n* `already_fixed` - Already fixed\n* `report_unclear` - Report is unclear to me\n* `analysis_wrong` - Agent's analysis is wrong\n* `wontfix_intentional` - Won't fix - intentional behavior\n* `wontfix_irrelevant` - Won't fix - issue is real but insignificant\n* `other` - Something else…"
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
        .array(zod.string())
        .max(signalsReportsBulkStateCreateBodyIdsMax)
        .describe(
            'Report ids to transition to `state` in one call (1–100). Duplicates are de-duplicated; each id is processed independently so one disallowed transition does not block the rest. `dismissal_reason`, `dismissal_note` and `snooze_for` apply to every id.'
        ),
})

/**
 * List the per-(team, skill) scout configs for this project — schedule (`run_interval_minutes`), `enabled`, and `emit` posture per scout. A freshly authored scout skill appears here once its config is registered, either explicitly via create or by the coordinator's next tick.
 * @summary List scout configs
 */
export const SignalsScoutConfigListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Register the config for a `signals-scout-*` skill immediately, without waiting for the coordinator to auto-register it — optionally setting `run_interval_minutes`, `enabled`, and `emit` in the same call. The skill must already exist on this project. Upsert: if a config already exists for the skill, the provided fields are applied to it.
 * @summary Create a scout config
 */
export const SignalsScoutConfigCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutConfigCreateBodySkillNameMax = 200

export const signalsScoutConfigCreateBodyRunIntervalMinutesMin = 30
export const signalsScoutConfigCreateBodyRunIntervalMinutesMax = 43200

export const SignalsScoutConfigCreateBody = /* @__PURE__ */ zod
    .object({
        skill_name: zod
            .string()
            .max(signalsScoutConfigCreateBodySkillNameMax)
            .describe(
                'The `signals-scout-*` skill to register a config for. The skill must already exist on this project — author it via the skills store first.'
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
export const SignalsScoutConfigUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this Signal scout config.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
        'Per-(team, skill) scout config: schedule, enablement, and emit posture.\n\nOne row per `signals-scout-*` skill on the team. The coordinator auto-creates a row\nwhen it discovers a scout skill; this serializer lets agents tune the row.'
    )

/**
 * Delete one scout config by its `id`, removing the per-(team, skill) schedule/emit row outright. The point is cleaning up an orphaned config whose `signals-scout-*` skill was archived or deleted — it lingers in `list` with an empty `description`, never runs (the coordinator skips it and the skill can't load), but can't otherwise be removed over the API. Deletion is activity-logged. Note: if the skill still exists, the coordinator re-creates a default-schedule config on its next tick — to retire a live scout, archive its skill (or set `enabled=false` to make it inert) rather than deleting the config.
 * @summary Delete a scout config
 */
export const SignalsScoutConfigDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this Signal scout config.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Dispatch one on-demand run of this scout immediately, regardless of its schedule. Useful to test a scout right after authoring it, or to refresh its findings on demand. The run executes asynchronously on the worker and inherits every guard the scheduled path has: it is forbidden if scouts are not enabled for the project (403), and skipped if the project is over its Signals credits quota or daily run budget (429) or a run for this scout is already in progress (409). A manual run counts against the same daily run budget as scheduled runs, so repeated manual runs of the same scout can exhaust the project's daily allowance. A manual run does not change the scout's schedule or `last_run_at`. A disabled scout can still be run this way (to test before enabling). Returns immediately with the workflow id — poll the scout's runs for the result.
 * @summary Run a scout now
 */
export const SignalsScoutConfigRunParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this Signal scout config.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Materialize the scout fleet for this project on demand (idempotent): seed the canonical `signals-scout-*` skills, create a default-schedule config for any scout lacking one, and return all scout configs. Normally the Temporal coordinator does this on its next tick; this action exists so setup flows (e.g. the wizard's self-driving program) can hand the user a tunable fleet immediately.
 * @summary Sync scout configs
 */
export const SignalsScoutConfigSyncParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Return the people who can review work on this project — one row per member with access to it, each with their `user_uuid`, `email`, `first_name`/`last_name`, and resolved GitHub `login` (null when they have no linked GitHub identity). The cold-start reviewer-routing path: when a finding's owner can't be read off a fetched entity's `created_by` and there's no cached `reviewer:<area>` memory or inbox precedent, list members, match the owner by email/name, then put their resolved `github_login` in `suggested_reviewers` on `emit-report` / `edit-report`. Pass `search` to narrow a large roster; the result is capped at 200. Strictly team-scoped.
 * @summary List project members for reviewer routing
 */
export const SignalsScoutMembersListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SignalsScoutMembersListQueryParams = /* @__PURE__ */ zod.object({
    search: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Case-insensitive substring filter over member email and first/last name. Use it to narrow a large project's roster to the owner you're trying to match instead of pulling every member."
        ),
})

/**
 * Return the team's deterministic project profile. For the internal scout token the response reflects the newest non-expired cached row or a freshly-built one (lazy compute on cache miss); `force_refresh=true` skips the cache and rebuilds from authoritative sources. Public read callers (session auth or a `signal_scout:read` PAK) get the newest cached profile, or 404 if none has been built yet — they never trigger a rebuild. Read this at the start of a run to orient on the team's product mix, integrations, warehouse sources, signal coverage, and existing inbox surface.
 * @summary Get the current project profile
 */
export const SignalsScoutProjectProfileGetParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutProjectProfileGetQueryForceRefreshDefault = false

export const SignalsScoutProjectProfileGetQueryParams = /* @__PURE__ */ zod.object({
    force_refresh: zod
        .boolean()
        .default(signalsScoutProjectProfileGetQueryForceRefreshDefault)
        .describe(
            "When true, skip the cache and rebuild the profile from authoritative sources before responding. Use after seeding events, importing data, or any other change the caller knows just landed but hasn't surfaced through natural cache expiry yet. Honored only for the internal scout token — public read callers get the cached profile regardless. Concurrent forced rebuilds are serialized by the team-keyed advisory lock — at most one extra `build_inventory` per simultaneous request."
        ),
})

/**
 * Return the most recent `SignalScoutRun` summaries for this project, newest first. Used by the headless scout to dedupe against work other runs already covered. ILIKE matches on `summary`. `date_from` / `date_to` are a half-open window on `created_at` (`>= date_from`, `< date_to`); pass `date_to` on subsequent calls to walk past the 100-row cap. Pass `emitted=true` to see only runs that surfaced at least one finding. Pass `skill_name` (optionally with `skill_version`) to scope to a single scout. Results capped at 100.
 * @summary Search recent agent runs
 */
export const SignalsScoutRunsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutRunsListQueryLimitMax = 100

export const SignalsScoutRunsListQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('ISO-8601 inclusive lower bound on `created_at`. Omit to skip the lower bound.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'ISO-8601 exclusive upper bound on `created_at`. Pass to walk back past the result cap on subsequent calls (cursor-style: set to the `created_at` of the oldest run from the prior page).'
        ),
    emitted: zod
        .boolean()
        .nullish()
        .describe(
            'Filter by emit outcome. `true` returns only runs that emitted at least one finding (`emitted_count > 0`); `false` returns only runs that emitted nothing. Omit for both.'
        ),
    limit: zod
        .number()
        .min(1)
        .max(signalsScoutRunsListQueryLimitMax)
        .optional()
        .describe('Max rows to return (default 20, hard cap 100).'),
    skill_name: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'Exact-match filter on the scout skill (e.g. `signals-scout-errors`). Narrows the run dump to a single scout — the primary scoping path when a specialist dedupes against its own past runs. Omit to span every scout on the team.'
        ),
    skill_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Exact-match filter on the skill version. Pair with `skill_name` to pin one version; omit for all.'),
    text: zod
        .string()
        .min(1)
        .optional()
        .describe("Case-insensitive substring match on the scout's end-of-run `summary`. Omit to skip the filter."),
})

/**
 * Return the full `SignalScoutRun` row. Status, timing, and error flow from the linked `tasks.TaskRun`. Strictly team-scoped — a UUID belonging to another team returns 404.
 * @summary Get a run by ID
 */
export const SignalsScoutRunsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string().describe('UUID of the `SignalScoutRun` bridge row.'),
})

/**
 * Rewrite a report's title/summary, append a note, and/or set its suggested reviewers. Can target ANY of the project's inbox reports, not just scout-authored ones — so the edit is attributed to this scout. Setting reviewers is how you rescue a report that surfaced routed to no one: it replaces the reviewer list and re-runs autostart, so a report missing a qualifying reviewer can open a draft PR. Title/summary edits are best-effort: the pipeline may later re-research them.
 * @summary Edit an existing report for a run
 */
export const SignalsScoutEditReportParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string().describe('UUID of the `SignalScoutRun` bridge row.'),
})

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
                'Optional new title. Conventional-commit style (`type(scope): description`) renders with type/scope styling. The pipeline may later re-research and overwrite it.'
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
                            .string()
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
                'Optional reviewers to set on the report (each a `github_login` and/or `user_uuid`), replacing any existing list. Use this to route a report that surfaced with no reviewer — it re-runs autostart, so a report that was missing a qualifying reviewer can now open a draft PR. An empty list is a no-op (existing reviewers are left untouched, never cleared).'
            ),
    })
    .describe(
        "Request body for `edit-report`. Can target ANY of the team's inbox reports, not just scout-authored ones."
    )

/**
 * Return the findings a `SignalScoutRun` emitted to the inbox, newest first — one row per emit with its `description` (the finding text as surfaced), `weight`, `confidence`, `severity`, and the deterministic `source_id` that joins back to the underlying signal. Lets a team and its agents see *what* a run surfaced without parsing `emitted_finding_ids` or scanning the signal store. Strictly team-scoped — a run UUID belonging to another team returns 404.
 * @summary List a run's emitted findings
 */
export const SignalsScoutRunsEmissionsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string().describe('UUID of the `SignalScoutRun` bridge row.'),
})

/**
 * Best-effort reverse of the report -> signals link. For each finding the run emitted, resolve the inbox `SignalReport` (if any) its underlying signal grouped into by walking the deterministic `source_id` back through the signal store. `report` is null when the finding hasn't grouped into a report yet, was de-duplicated away, or its signal was deleted. Lets the scout UI surface which inbox report a finding contributed to — the reverse of the report's evidence list. Strictly team-scoped — a run UUID belonging to another team returns 404.
 * @summary List the inbox reports a run's findings linked to
 */
export const SignalsScoutRunsEmissionReportsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string().describe('UUID of the `SignalScoutRun` bridge row.'),
})

/**
 * The second emit channel: author a complete `SignalReport` directly instead of emitting a weak signal. The report passes the safety judge, then surfaces at the status the scout's `actionability` call implies (or is suppressed). Backing `evidence` is written as bound signals so the report behaves like a pipeline report. NOT idempotent — a retry authors a second report; use `reports` to find a prior report and `edit-report` to update it instead.
 * @summary Author a full report for a run
 */
export const SignalsScoutEmitReportParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string().describe('UUID of the `SignalScoutRun` bridge row.'),
})

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
                'One-line report title the inbox shows. Conventional-commit style (`type(scope): description`, e.g. `fix(insights): missing series color`) renders with type/scope styling.'
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
                                'Prose for this observation. Embedded and rendered to the safety/research surfaces.'
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
                '* `immediately_actionable` - immediately_actionable\n* `requires_human_input` - requires_human_input\n* `not_actionable` - not_actionable'
            )
            .describe(
                "The scout's actionability call: `immediately_actionable` -> the report surfaces READY; `requires_human_input` -> PENDING_INPUT; `not_actionable` -> suppressed. A safety-judge failure suppresses the report regardless.\n\n* `immediately_actionable` - immediately_actionable\n* `requires_human_input` - requires_human_input\n* `not_actionable` - not_actionable"
            ),
        already_addressed: zod
            .boolean()
            .default(signalsScoutEmitReportBodyAlreadyAddressedDefault)
            .describe('Whether the issue already appears fixed in recent changes (tracked separately).'),
        repository: zod
            .string()
            .nullish()
            .describe(
                "Optional repo for autostart (opening a draft PR): `owner/repo` targets that repo, the `NO_REPO` sentinel opts out (report lands without a PR), and omitting it triggers free-form selection across the team's repos — the slow path on a many-repo team, so pass `owner/repo` when you know it."
            ),
        priority: zod
            .union([
                zod
                    .enum(['P0', 'P1', 'P2', 'P3', 'P4'])
                    .describe('* `P0` - P0\n* `P1` - P1\n* `P2` - P2\n* `P3` - P3\n* `P4` - P4'),
                zod.null(),
            ])
            .optional()
            .describe(
                'Optional priority (`P0`-`P4`). Required for autostart; pair with `priority_explanation`.\n\n* `P0` - P0\n* `P1` - P1\n* `P2` - P2\n* `P3` - P3\n* `P4` - P4'
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
                            .string()
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
                "Optional reviewers to route the report to (each a `github_login` and/or `user_uuid`). This is the primary way a report reaches a human — the inbox floats a reviewer's own reports to the top of their inbox even when no PR is involved — so set it whenever you can name a plausible owner. It also gates autostart: a PR opens only if at least one reviewer clears their autonomy threshold."
            ),
    })
    .describe('Request body for `emit-report`. Run attribution is taken from the URL path.')

/**
 * Fire `emit_signal` with `source_product = signals_scout`. The `finding_id` is baked into the deterministic `Signal.source_id = run:<id>:finding:<id>` for traceability, but this is NOT idempotent — a second call with the same `finding_id` emits a second signal, so do not retry an emit that may have already succeeded.
 * @summary Emit a finding for a run
 */
export const SignalsScoutEmitSignalParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    run_id: zod.string().describe('UUID of the `SignalScoutRun` bridge row.'),
})

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
                    .describe('* `P0` - P0\n* `P1` - P1\n* `P2` - P2\n* `P3` - P3\n* `P4` - P4'),
                zod.null(),
            ])
            .optional()
            .describe(
                'Optional severity tag — one of P0, P1, P2, P3, P4. Informational only.\n\n* `P0` - P0\n* `P1` - P1\n* `P2` - P2\n* `P3` - P3\n* `P4` - P4'
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
 * Return the team's recently emitted scout findings across *every* run, newest first — the cross-run counterpart to the per-run `emissions` action. Each row carries its `run_id`, so you can regroup by run without first listing runs and fanning out one `emissions` call each. Pass `skill_name` to scope to a single scout, and `date_from` / `date_to` (a half-open window on `emitted_at`) to bound or paginate — set `date_to` to the oldest emission's `emitted_at` to walk back past the limit. Pure Postgres, no ClickHouse round-trip. Capped at 200 rows (default 50).
 * @summary List recent emitted findings across all runs
 */
export const SignalsScoutRunsRecentEmissionsParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutRunsRecentEmissionsQueryLimitMax = 200

export const SignalsScoutRunsRecentEmissionsQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('ISO-8601 inclusive lower bound on `emitted_at`. Omit to skip the lower bound.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'ISO-8601 exclusive upper bound on `emitted_at`. Pass to walk back past the result cap on subsequent calls (cursor-style: set to the `emitted_at` of the oldest emission from the prior page).'
        ),
    limit: zod
        .number()
        .min(1)
        .max(signalsScoutRunsRecentEmissionsQueryLimitMax)
        .optional()
        .describe('Max rows to return (default 50, hard cap 200).'),
    skill_name: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Exact-match filter on the emitting scout's skill (e.g. `signals-scout-errors`). Narrows to findings one specialist surfaced; omit to span every scout on the team."
        ),
})

/**
 * Return `SignalScratchpad` entries for this project, newest-first. ILIKE matches on `content` and `key`. `date_from` / `date_to` are a half-open window on `updated_at` (`>= date_from`, `< date_to`); pass `date_to` (the `updated_at` of the oldest entry seen) on subsequent calls to walk past the cap. Pass `keys_only=true` to scan keys without pulling entry bodies, or `content_max_chars` to cap each `content` to a preview — both keep a wide orientation scan from returning every entry's full prose. Results capped at 500.
 * @summary Search the scout scratchpad
 */
export const SignalsScoutScratchpadSearchParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutScratchpadSearchQueryContentMaxCharsMin = 0

export const signalsScoutScratchpadSearchQueryLimitMax = 500

export const SignalsScoutScratchpadSearchQueryParams = /* @__PURE__ */ zod.object({
    content_max_chars: zod
        .number()
        .min(signalsScoutScratchpadSearchQueryContentMaxCharsMin)
        .optional()
        .describe(
            "Truncate each entry's `content` to the first N characters (a preview). Omit for the full body. Ignored when `keys_only=true`."
        ),
    date_from: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe('ISO-8601 inclusive lower bound on `updated_at`. Omit to skip the lower bound.'),
    date_to: zod.iso
        .datetime({ offset: true })
        .optional()
        .describe(
            'ISO-8601 exclusive upper bound on `updated_at`. Pass to walk back past the result cap on subsequent calls (cursor-style: set to the `updated_at` of the oldest entry from the prior page).'
        ),
    keys_only: zod
        .boolean()
        .optional()
        .describe(
            "When true, blank each entry's `content` and return only keys + metadata. Use to scan which memories exist without pulling their (potentially large) bodies, then re-query the ones worth a full read. Takes precedence over `content_max_chars`."
        ),
    limit: zod
        .number()
        .min(1)
        .max(signalsScoutScratchpadSearchQueryLimitMax)
        .optional()
        .describe('Max rows to return (default 20, hard cap 500).'),
    text: zod
        .string()
        .optional()
        .describe('ILIKE substring match against `content`. Omit to return the most recent entries.'),
})

/**
 * Upsert a memory keyed on `(team, key)`. Re-using a key updates the existing entry in place.
 * @summary Remember a scratchpad entry
 */
export const SignalsScoutScratchpadRememberParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutScratchpadRememberBodyKeyMax = 300

export const signalsScoutScratchpadRememberBodyContentMax = 50000

export const SignalsScoutScratchpadRememberBody = /* @__PURE__ */ zod
    .object({
        key: zod
            .string()
            .max(signalsScoutScratchpadRememberBodyKeyMax)
            .describe(
                "Agent-chosen semantic key, unique per team; re-using a key overwrites the entry in place. Key off the *stable identity* of what you're tracking — never embed a date, timestamp, or run id (that mints a new row every run and breaks dedupe). For run state/cursors, use one fixed key and keep the timestamp in `content`."
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
export const SignalsScoutScratchpadForgetParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const signalsScoutScratchpadForgetBodyKeyMax = 300

export const SignalsScoutScratchpadForgetBody = /* @__PURE__ */ zod
    .object({
        key: zod.string().max(signalsScoutScratchpadForgetBodyKeyMax).describe('Memory key to delete.'),
    })
    .describe('Request body for `forget`.')

export const SignalsSourceConfigsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SignalsSourceConfigsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const SignalsSourceConfigsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
        ])
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking\n* `pganalyze` - pganalyze\n* `signals_scout` - Signals scout\n* `logs` - Logs\n* `health_checks` - Health checks\n* `endpoints` - Endpoints\n* `replay_vision` - Replay Vision'
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
        ])
        .describe(
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `evaluation_report` - Evaluation report\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking\n* `cross_source_issue` - Cross source issue\n* `alert_state_change` - Alert state change\n* `health_issue` - Health issue\n* `endpoint_execution_failed` - Endpoint execution failed\n* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n* `scanner_finding` - Scanner finding'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

export const SignalsSourceConfigsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal source config.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const SignalsSourceConfigsUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal source config.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
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
        ])
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking\n* `pganalyze` - pganalyze\n* `signals_scout` - Signals scout\n* `logs` - Logs\n* `health_checks` - Health checks\n* `endpoints` - Endpoints\n* `replay_vision` - Replay Vision'
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
        ])
        .describe(
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `evaluation_report` - Evaluation report\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking\n* `cross_source_issue` - Cross source issue\n* `alert_state_change` - Alert state change\n* `health_issue` - Health issue\n* `endpoint_execution_failed` - Endpoint execution failed\n* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n* `scanner_finding` - Scanner finding'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})

export const SignalsSourceConfigsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this signal source config.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
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
        ])
        .optional()
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking\n* `pganalyze` - pganalyze\n* `signals_scout` - Signals scout\n* `logs` - Logs\n* `health_checks` - Health checks\n* `endpoints` - Endpoints\n* `replay_vision` - Replay Vision'
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
        ])
        .optional()
        .describe(
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `evaluation_report` - Evaluation report\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking\n* `cross_source_issue` - Cross source issue\n* `alert_state_change` - Alert state change\n* `health_issue` - Health issue\n* `endpoint_execution_failed` - Endpoint execution failed\n* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded\n* `scanner_finding` - Scanner finding'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})
