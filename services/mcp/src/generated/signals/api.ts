/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 20 enabled ops
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
 *     "dismissal_reason": "<any string code, owned by the caller>",
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
        .string()
        .optional()
        .describe(
            "Optional short reason code for the dismissal (e.g. 'not_a_bug', 'wont_fix', 'duplicate'). The set of reason codes is owned by the caller and is not validated server-side."
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

export const signalsScoutConfigCreateBodyRunIntervalMinutesMin = 10
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
            .describe('Minutes between runs (10–43200). Defaults to 60 (hourly).'),
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

export const signalsScoutConfigUpdateBodyRunIntervalMinutesMin = 10
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
                'Minutes between runs (10–43200). The scout runs once this interval has elapsed since its last run.'
            ),
    })
    .describe(
        'Per-(team, skill) scout config: schedule, enablement, and emit posture.\n\nOne row per `signals-scout-*` skill on the team. The coordinator auto-creates a row\nwhen it discovers a scout skill; this serializer lets agents tune the row.'
    )

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
            'ISO-8601 exclusive upper bound on `created_at`. Pass to walk back past the result cap on subsequent calls (cursor-style: set to the `started_at` of the oldest run from the prior page).'
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
 * Return `SignalScratchpad` entries for this project. ILIKE matches on `content` and `key`. Pass `keys_only=true` to scan keys without pulling entry bodies, or `content_max_chars` to cap each `content` to a preview — both keep a wide orientation scan from returning every entry's full prose.
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

export const signalsScoutScratchpadSearchQueryLimitMax = 100

export const SignalsScoutScratchpadSearchQueryParams = /* @__PURE__ */ zod.object({
    content_max_chars: zod
        .number()
        .min(signalsScoutScratchpadSearchQueryContentMaxCharsMin)
        .optional()
        .describe(
            "Truncate each entry's `content` to the first N characters (a preview). Omit for the full body. Ignored when `keys_only=true`."
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
        .describe('Max rows to return (default 20, hard cap 100).'),
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
            .describe('Agent-chosen semantic key. Re-using a key updates the existing entry in place.'),
        content: zod
            .string()
            .max(signalsScoutScratchpadRememberBodyContentMax)
            .describe('Prose to write. Read verbatim into future prompts.'),
        run_id: zod
            .uuid()
            .nullish()
            .describe(
                'Run that authored this memory; persisted as `created_by_run_id` for lineage. Must reference a run on this same project — cross-project run UUIDs are rejected.'
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
        ])
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking\n* `pganalyze` - pganalyze\n* `signals_scout` - Signals scout\n* `logs` - Logs\n* `health_checks` - Health checks\n* `endpoints` - Endpoints'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation',
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
        ])
        .describe(
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking\n* `cross_source_issue` - Cross source issue\n* `alert_state_change` - Alert state change\n* `health_issue` - Health issue\n* `endpoint_execution_failed` - Endpoint execution failed\n* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded'
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
        ])
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking\n* `pganalyze` - pganalyze\n* `signals_scout` - Signals scout\n* `logs` - Logs\n* `health_checks` - Health checks\n* `endpoints` - Endpoints'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation',
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
        ])
        .describe(
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking\n* `cross_source_issue` - Cross source issue\n* `alert_state_change` - Alert state change\n* `health_issue` - Health issue\n* `endpoint_execution_failed` - Endpoint execution failed\n* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded'
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
        ])
        .optional()
        .describe(
            '* `session_replay` - Session replay\n* `llm_analytics` - LLM analytics\n* `github` - GitHub\n* `linear` - Linear\n* `zendesk` - Zendesk\n* `conversations` - Conversations\n* `error_tracking` - Error tracking\n* `pganalyze` - pganalyze\n* `signals_scout` - Signals scout\n* `logs` - Logs\n* `health_checks` - Health checks\n* `endpoints` - Endpoints'
        ),
    source_type: zod
        .enum([
            'session_analysis_cluster',
            'evaluation',
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
        ])
        .optional()
        .describe(
            '* `session_analysis_cluster` - Session analysis cluster\n* `evaluation` - Evaluation\n* `issue` - Issue\n* `ticket` - Ticket\n* `issue_created` - Issue created\n* `issue_reopened` - Issue reopened\n* `issue_spiking` - Issue spiking\n* `cross_source_issue` - Cross source issue\n* `alert_state_change` - Alert state change\n* `health_issue` - Health issue\n* `endpoint_execution_failed` - Endpoint execution failed\n* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded'
        ),
    enabled: zod.boolean().optional(),
    config: zod.unknown().optional(),
})
