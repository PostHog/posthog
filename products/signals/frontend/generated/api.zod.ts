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
 * Register the config for a `signals-scout-*` skill immediately, without waiting for the coordinator to auto-register it — optionally setting `run_interval_minutes`, `enabled`, and `emit` in the same call. The skill must already exist on this project. Upsert: if a config already exists for the skill, the provided fields are applied to it.
 * @summary Create a scout config
 */
export const signalsScoutConfigCreateBodySkillNameMax = 200

export const signalsScoutConfigCreateBodyRunIntervalMinutesMin = 10
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
            .describe('Minutes between runs (10–43200). Defaults to 60 (hourly).'),
    })
    .describe(
        'Request body for registering a scout config without waiting for the coordinator tick.\n\nUpsert keyed on `skill_name`: if the coordinator (or a concurrent caller) already\nregistered the row, the provided tunables are applied to it instead.'
    )

/**
 * Tune one scout: change its schedule (`run_interval_minutes`), `enabled`, or `emit` (dry-run) posture. `skill_name` is fixed. Enabling records `enabled_by` and is activity-logged since it drives spend.
 * @summary Update a scout config
 */
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
        'Per-(team, skill) scout config: schedule, enablement, and emit posture.\n\nOne row per `signals-scout-\*` skill on the team. The coordinator auto-creates a row\nwhen it discovers a scout skill; this serializer lets agents tune the row.'
    )

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
        ])
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints'
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
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded'
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
        ])
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints'
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
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded'
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
        ])
        .optional()
        .describe(
            '\* `session_replay` - Session replay\n\* `llm_analytics` - LLM analytics\n\* `github` - GitHub\n\* `linear` - Linear\n\* `zendesk` - Zendesk\n\* `conversations` - Conversations\n\* `error_tracking` - Error tracking\n\* `pganalyze` - pganalyze\n\* `signals_scout` - Signals scout\n\* `logs` - Logs\n\* `health_checks` - Health checks\n\* `endpoints` - Endpoints'
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
            '\* `session_analysis_cluster` - Session analysis cluster\n\* `evaluation` - Evaluation\n\* `issue` - Issue\n\* `ticket` - Ticket\n\* `issue_created` - Issue created\n\* `issue_reopened` - Issue reopened\n\* `issue_spiking` - Issue spiking\n\* `cross_source_issue` - Cross source issue\n\* `alert_state_change` - Alert state change\n\* `health_issue` - Health issue\n\* `endpoint_execution_failed` - Endpoint execution failed\n\* `endpoint_breakdown_limit_exceeded` - Endpoint breakdown limit exceeded'
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
