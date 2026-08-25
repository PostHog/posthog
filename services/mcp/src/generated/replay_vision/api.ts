/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 29 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const VisionActionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionActionsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    scanner: zod.string().optional().describe('Filter to the actions belonging to one scanner.'),
})

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const VisionActionsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionActionsCreateBodyNameMax = 255

export const visionActionsCreateBodyTriggerConfigOneTimezoneDefault = `UTC`
export const visionActionsCreateBodySynthesisConfigOnePromptGuideMax = 500

export const visionActionsCreateBodyAlertConfigOneFrequencyDefault = `on_breach`
export const visionActionsCreateBodyAlertConfigOneMetricDefault = `count`
export const visionActionsCreateBodyAlertConfigOneDirectionDefault = `above`
export const visionActionsCreateBodyAlertConfigOneIncludeReasoningDefault = false

export const VisionActionsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(visionActionsCreateBodyNameMax)
            .describe('Human-readable action name. Unique within the team.'),
        scanner: zod
            .string()
            .describe('Scanner whose observations this action operates on. Must belong to the same team.'),
        enabled: zod.boolean().optional().describe('When false, the scheduler skips this action.'),
        is_scanner_digest: zod
            .boolean()
            .optional()
            .describe(
                "Marks this action as the scanner's built-in daily digest, the one summary surfaced on the scanner overview. At most one digest per scanner."
            ),
        trigger_type: zod
            .enum(['schedule', 'threshold'])
            .describe('\* `schedule` - Schedule\n\* `threshold` - Threshold')
            .optional()
            .describe(
                "What fires the action. MVP supports 'schedule' only.\n\n\* `schedule` - Schedule\n\* `threshold` - Threshold"
            ),
        mode: zod
            .enum(['group_summary', 'alert', 'per_observation'])
            .describe('\* `group_summary` - Group summary\n\* `alert` - Alert\n\* `per_observation` - Per observation')
            .optional()
            .describe(
                "What the action produces. MVP supports 'group_summary' only.\n\n\* `group_summary` - Group summary\n\* `alert` - Alert\n\* `per_observation` - Per observation"
            ),
        trigger_config: zod
            .object({
                rrule: zod
                    .string()
                    .optional()
                    .describe(
                        'iCal RRULE string controlling the schedule cadence (no DTSTART — the start is managed separately).'
                    ),
                timezone: zod
                    .string()
                    .default(visionActionsCreateBodyTriggerConfigOneTimezoneDefault)
                    .describe("IANA timezone name the RRULE is expanded in, e.g. 'Europe\/Prague'. Defaults to 'UTC'."),
            })
            .describe('Schedule trigger parameters. Threshold triggers are reserved and rejected at the API for now.')
            .optional()
            .describe('Trigger parameters. For schedule triggers: {rrule, timezone}.'),
        selection: zod
            .object({
                scanner_ids: zod
                    .array(zod.string())
                    .optional()
                    .describe('Restrict to observations produced by these scanner IDs. Defaults to the bound scanner.'),
                verdict: zod
                    .array(
                        zod
                            .enum(['yes', 'no', 'inconclusive'])
                            .describe('\* `yes` - yes\n\* `no` - no\n\* `inconclusive` - inconclusive')
                    )
                    .optional()
                    .describe('Only run on monitor observations with one of these verdicts (yes\/no\/inconclusive).'),
                tags: zod
                    .array(zod.string())
                    .optional()
                    .describe('Only run on classifier observations carrying any of these tags (fixed or freeform).'),
                min_score: zod
                    .number()
                    .optional()
                    .describe('Only run on scorer observations with a score at or above this value (inclusive).'),
                max_score: zod
                    .number()
                    .optional()
                    .describe('Only run on scorer observations with a score at or below this value (inclusive).'),
            })
            .describe(
                'The action\'s targeting predicate (\"run this on…\") applied when gathering observations. All keys\noptional; this typed shape is the allowlist, so unknown input keys are dropped rather than persisted.'
            )
            .optional()
            .describe("Targeting predicate: which of the scanner's observations this action runs on."),
        synthesis_config: zod
            .object({
                prompt_guide: zod
                    .string()
                    .max(visionActionsCreateBodySynthesisConfigOnePromptGuideMax)
                    .optional()
                    .describe('Free-form guidance steering how the group summary is written.'),
            })
            .describe('Options for the group-summary synthesis step.')
            .optional()
            .describe('Synthesis options for the group summary, e.g. {prompt_guide}.'),
        alert_config: zod
            .object({
                frequency: zod
                    .enum(['every_match', 'on_breach'])
                    .describe('\* `every_match` - Every new match\n\* `on_breach` - When a threshold is crossed')
                    .default(visionActionsCreateBodyAlertConfigOneFrequencyDefault)
                    .describe(
                        "'every_match' notifies about every new matching observation (batched per check); 'on_breach' notifies once when the threshold condition starts holding. Defaults to 'on_breach'.\n\n\* `every_match` - Every new match\n\* `on_breach` - When a threshold is crossed"
                    ),
                metric: zod
                    .enum(['count', 'avg_score'])
                    .describe('\* `count` - Count of matching observations\n\* `avg_score` - Average score')
                    .default(visionActionsCreateBodyAlertConfigOneMetricDefault)
                    .describe(
                        "What to measure over the window: 'count' of targeted observations, or 'avg_score' (the mean scorer score; scorer scanners only). every_match supports 'count' only.\n\n\* `count` - Count of matching observations\n\* `avg_score` - Average score"
                    ),
                threshold: zod
                    .number()
                    .optional()
                    .describe(
                        "The alert fires when the metric is at or above ('above') or at or below ('below') this value, per 'direction'. Required for on_breach; ignored for every_match."
                    ),
                direction: zod
                    .enum(['above', 'below'])
                    .describe('\* `above` - At or above\n\* `below` - At or below')
                    .default(visionActionsCreateBodyAlertConfigOneDirectionDefault)
                    .describe(
                        "Which side of the threshold breaches: 'above' fires when the metric is at or above it, 'below' when at or below (e.g. an average score dropping under a floor). Both inclusive. Defaults to 'above'; ignored for every_match.\n\n\* `above` - At or above\n\* `below` - At or below"
                    ),
                window_days: zod
                    .union([zod.literal(1), zod.literal(3), zod.literal(7), zod.literal(14), zod.literal(30)])
                    .describe('\* `1` - 1 day\n\* `3` - 3 days\n\* `7` - 7 days\n\* `14` - 14 days\n\* `30` - 30 days')
                    .optional()
                    .describe(
                        "Rolling lookback window for on_breach conditions, ending at each check. Defaults to 1 day. every_match ignores it (each check covers what's new since the previous one).\n\n\* `1` - 1 day\n\* `3` - 3 days\n\* `7` - 7 days\n\* `14` - 14 days\n\* `30` - 30 days"
                    ),
                include_reasoning: zod
                    .boolean()
                    .default(visionActionsCreateBodyAlertConfigOneIncludeReasoningDefault)
                    .describe(
                        "When true, each example line in the alert message includes the scanner's full reasoning for that observation, not just its verdict\/score\/tags. Useful when piping the message somewhere else to read or act on. Defaults to false."
                    ),
            })
            .describe(
                "The alert condition for mode='alert', applied after `selection` targeting. 'every_match'\nnotifies about each new match since the previous check; 'on_breach' compares a metric to a\nthreshold over a rolling window and notifies on the transition into breach."
            )
            .optional()
            .describe("Alert condition; required when mode is 'alert', ignored otherwise."),
        delivery_config: zod
            .array(
                zod
                    .object({
                        type: zod
                            .enum(['slack', 'webhook'])
                            .describe('\* `slack` - Slack\n\* `webhook` - Webhook')
                            .describe(
                                "Destination type: 'slack' posts to a Slack channel; 'webhook' POSTs a JSON payload to a URL.\n\n\* `slack` - Slack\n\* `webhook` - Webhook"
                            ),
                        integration_id: zod
                            .number()
                            .optional()
                            .describe(
                                "ID of the Slack Integration on this team used to deliver. Required when type is 'slack'."
                            ),
                        channel: zod
                            .string()
                            .optional()
                            .describe(
                                "Slack channel ID or name the summary is posted to. Required when type is 'slack'."
                            ),
                        url: zod
                            .url()
                            .optional()
                            .describe(
                                "HTTPS endpoint the summary is POSTed to as JSON. Required when type is 'webhook'. Redacted to scheme+host in responses for users without editor access to the scanner."
                            ),
                    })
                    .describe('A single delivery destination: a Slack channel or an HTTP webhook URL.')
            )
            .optional()
            .describe('List of delivery destinations the synthesized summary is sent to.'),
    })
    .describe('A Replay Vision action: a scheduled \"and then…\" automation over a scanner\'s observations.')

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const VisionActionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this vision action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const VisionActionsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this vision action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionActionsPartialUpdateBodyNameMax = 255

export const visionActionsPartialUpdateBodyTriggerConfigOneTimezoneDefault = `UTC`
export const visionActionsPartialUpdateBodySynthesisConfigOnePromptGuideMax = 500

export const visionActionsPartialUpdateBodyAlertConfigOneFrequencyDefault = `on_breach`
export const visionActionsPartialUpdateBodyAlertConfigOneMetricDefault = `count`
export const visionActionsPartialUpdateBodyAlertConfigOneDirectionDefault = `above`
export const visionActionsPartialUpdateBodyAlertConfigOneIncludeReasoningDefault = false

export const VisionActionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(visionActionsPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable action name. Unique within the team.'),
        scanner: zod
            .string()
            .optional()
            .describe('Scanner whose observations this action operates on. Must belong to the same team.'),
        enabled: zod.boolean().optional().describe('When false, the scheduler skips this action.'),
        is_scanner_digest: zod
            .boolean()
            .optional()
            .describe(
                "Marks this action as the scanner's built-in daily digest, the one summary surfaced on the scanner overview. At most one digest per scanner."
            ),
        trigger_type: zod
            .enum(['schedule', 'threshold'])
            .describe('\* `schedule` - Schedule\n\* `threshold` - Threshold')
            .optional()
            .describe(
                "What fires the action. MVP supports 'schedule' only.\n\n\* `schedule` - Schedule\n\* `threshold` - Threshold"
            ),
        mode: zod
            .enum(['group_summary', 'alert', 'per_observation'])
            .describe('\* `group_summary` - Group summary\n\* `alert` - Alert\n\* `per_observation` - Per observation')
            .optional()
            .describe(
                "What the action produces. MVP supports 'group_summary' only.\n\n\* `group_summary` - Group summary\n\* `alert` - Alert\n\* `per_observation` - Per observation"
            ),
        trigger_config: zod
            .object({
                rrule: zod
                    .string()
                    .optional()
                    .describe(
                        'iCal RRULE string controlling the schedule cadence (no DTSTART — the start is managed separately).'
                    ),
                timezone: zod
                    .string()
                    .default(visionActionsPartialUpdateBodyTriggerConfigOneTimezoneDefault)
                    .describe("IANA timezone name the RRULE is expanded in, e.g. 'Europe\/Prague'. Defaults to 'UTC'."),
            })
            .describe('Schedule trigger parameters. Threshold triggers are reserved and rejected at the API for now.')
            .optional()
            .describe('Trigger parameters. For schedule triggers: {rrule, timezone}.'),
        selection: zod
            .object({
                scanner_ids: zod
                    .array(zod.string())
                    .optional()
                    .describe('Restrict to observations produced by these scanner IDs. Defaults to the bound scanner.'),
                verdict: zod
                    .array(
                        zod
                            .enum(['yes', 'no', 'inconclusive'])
                            .describe('\* `yes` - yes\n\* `no` - no\n\* `inconclusive` - inconclusive')
                    )
                    .optional()
                    .describe('Only run on monitor observations with one of these verdicts (yes\/no\/inconclusive).'),
                tags: zod
                    .array(zod.string())
                    .optional()
                    .describe('Only run on classifier observations carrying any of these tags (fixed or freeform).'),
                min_score: zod
                    .number()
                    .optional()
                    .describe('Only run on scorer observations with a score at or above this value (inclusive).'),
                max_score: zod
                    .number()
                    .optional()
                    .describe('Only run on scorer observations with a score at or below this value (inclusive).'),
            })
            .describe(
                'The action\'s targeting predicate (\"run this on…\") applied when gathering observations. All keys\noptional; this typed shape is the allowlist, so unknown input keys are dropped rather than persisted.'
            )
            .optional()
            .describe("Targeting predicate: which of the scanner's observations this action runs on."),
        synthesis_config: zod
            .object({
                prompt_guide: zod
                    .string()
                    .max(visionActionsPartialUpdateBodySynthesisConfigOnePromptGuideMax)
                    .optional()
                    .describe('Free-form guidance steering how the group summary is written.'),
            })
            .describe('Options for the group-summary synthesis step.')
            .optional()
            .describe('Synthesis options for the group summary, e.g. {prompt_guide}.'),
        alert_config: zod
            .object({
                frequency: zod
                    .enum(['every_match', 'on_breach'])
                    .describe('\* `every_match` - Every new match\n\* `on_breach` - When a threshold is crossed')
                    .default(visionActionsPartialUpdateBodyAlertConfigOneFrequencyDefault)
                    .describe(
                        "'every_match' notifies about every new matching observation (batched per check); 'on_breach' notifies once when the threshold condition starts holding. Defaults to 'on_breach'.\n\n\* `every_match` - Every new match\n\* `on_breach` - When a threshold is crossed"
                    ),
                metric: zod
                    .enum(['count', 'avg_score'])
                    .describe('\* `count` - Count of matching observations\n\* `avg_score` - Average score')
                    .default(visionActionsPartialUpdateBodyAlertConfigOneMetricDefault)
                    .describe(
                        "What to measure over the window: 'count' of targeted observations, or 'avg_score' (the mean scorer score; scorer scanners only). every_match supports 'count' only.\n\n\* `count` - Count of matching observations\n\* `avg_score` - Average score"
                    ),
                threshold: zod
                    .number()
                    .optional()
                    .describe(
                        "The alert fires when the metric is at or above ('above') or at or below ('below') this value, per 'direction'. Required for on_breach; ignored for every_match."
                    ),
                direction: zod
                    .enum(['above', 'below'])
                    .describe('\* `above` - At or above\n\* `below` - At or below')
                    .default(visionActionsPartialUpdateBodyAlertConfigOneDirectionDefault)
                    .describe(
                        "Which side of the threshold breaches: 'above' fires when the metric is at or above it, 'below' when at or below (e.g. an average score dropping under a floor). Both inclusive. Defaults to 'above'; ignored for every_match.\n\n\* `above` - At or above\n\* `below` - At or below"
                    ),
                window_days: zod
                    .union([zod.literal(1), zod.literal(3), zod.literal(7), zod.literal(14), zod.literal(30)])
                    .describe('\* `1` - 1 day\n\* `3` - 3 days\n\* `7` - 7 days\n\* `14` - 14 days\n\* `30` - 30 days')
                    .optional()
                    .describe(
                        "Rolling lookback window for on_breach conditions, ending at each check. Defaults to 1 day. every_match ignores it (each check covers what's new since the previous one).\n\n\* `1` - 1 day\n\* `3` - 3 days\n\* `7` - 7 days\n\* `14` - 14 days\n\* `30` - 30 days"
                    ),
                include_reasoning: zod
                    .boolean()
                    .default(visionActionsPartialUpdateBodyAlertConfigOneIncludeReasoningDefault)
                    .describe(
                        "When true, each example line in the alert message includes the scanner's full reasoning for that observation, not just its verdict\/score\/tags. Useful when piping the message somewhere else to read or act on. Defaults to false."
                    ),
            })
            .describe(
                "The alert condition for mode='alert', applied after `selection` targeting. 'every_match'\nnotifies about each new match since the previous check; 'on_breach' compares a metric to a\nthreshold over a rolling window and notifies on the transition into breach."
            )
            .optional()
            .describe("Alert condition; required when mode is 'alert', ignored otherwise."),
        delivery_config: zod
            .array(
                zod
                    .object({
                        type: zod
                            .enum(['slack', 'webhook'])
                            .describe('\* `slack` - Slack\n\* `webhook` - Webhook')
                            .describe(
                                "Destination type: 'slack' posts to a Slack channel; 'webhook' POSTs a JSON payload to a URL.\n\n\* `slack` - Slack\n\* `webhook` - Webhook"
                            ),
                        integration_id: zod
                            .number()
                            .optional()
                            .describe(
                                "ID of the Slack Integration on this team used to deliver. Required when type is 'slack'."
                            ),
                        channel: zod
                            .string()
                            .optional()
                            .describe(
                                "Slack channel ID or name the summary is posted to. Required when type is 'slack'."
                            ),
                        url: zod
                            .url()
                            .optional()
                            .describe(
                                "HTTPS endpoint the summary is POSTed to as JSON. Required when type is 'webhook'. Redacted to scheme+host in responses for users without editor access to the scanner."
                            ),
                    })
                    .describe('A single delivery destination: a Slack channel or an HTTP webhook URL.')
            )
            .optional()
            .describe('List of delivery destinations the synthesized summary is sent to.'),
    })
    .describe('A Replay Vision action: a scheduled \"and then…\" automation over a scanner\'s observations.')

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const VisionActionsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this vision action.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Read-only run history for a single vision action (nested under /vision/actions/{action_id}/runs/).
 */
export const VisionActionsRunsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    vision_action_id: zod.string(),
})

export const VisionActionsRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Read-only run history for a single vision action (nested under /vision/actions/{action_id}/runs/).
 */
export const VisionActionsRunsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this vision action run.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    vision_action_id: zod.string(),
})

/**
 * Read-only access to a session's observations across every scanner the caller can read, for the replay-page dock.
 */
export const VisionObservationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionObservationsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .string()
        .optional()
        .describe(
            'Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.'
        ),
    session_id: zod.string().describe('Session recording id to return observations for.'),
})

/**
 * Retrieve one observation. Any list filters passed along (status, tags, order_by, …) scope the `previous_observation_id`/`next_observation_id` navigation to the matching, identically-ordered set — so prev/next from a filtered table stays within that filtered list.
 */
export const VisionObservationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionObservationsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    backfill_id: zod.string().optional().describe('Only observations dispatched by this backfill.'),
    date_from: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or after this time. Accepts ISO 8601 or a relative date like `-7d`; values without an explicit offset are interpreted in the project's timezone."
        ),
    date_to: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or before this time. Accepts ISO 8601 or a relative date like `-1d`; date-only values include the whole day, interpreted in the project's timezone."
        ),
    labeled: zod
        .string()
        .optional()
        .describe(
            'When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.'
        ),
    max_score: zod
        .number()
        .optional()
        .describe(
            'Filter scorer observations to those scoring at or below this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.'
        ),
    min_score: zod
        .number()
        .optional()
        .describe(
            'Filter scorer observations to those scoring at or above this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.'
        ),
    order_by: zod
        .string()
        .optional()
        .describe(
            'Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.'
        ),
    recording_subject: zod
        .string()
        .optional()
        .describe('Filter to observations whose person email contains this value (case-insensitive).'),
    session_id: zod
        .string()
        .optional()
        .describe('Filter to observations of one or more session recordings. Accepts a comma-separated list.'),
    status: zod.string().optional().describe('Filter by observation status. Accepts a comma-separated list.'),
    tags: zod
        .string()
        .optional()
        .describe(
            'Filter classifier observations whose fixed or freeform tags include any of the given values (comma-separated). Matches if the tag appears in either `tags` or `tags_freeform`.'
        ),
    triggered_by: zod
        .string()
        .optional()
        .describe(
            'Filter by trigger source (schedule, on_demand, retry, or backfill). Accepts a comma-separated list.'
        ),
    verdict: zod
        .string()
        .optional()
        .describe('Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).'),
})

/**
 * Set or update the observation's shared label: whether the scanner scored the session correctly, plus optional feedback on what it got wrong. One label per observation, shared across the team; these labels feed prompt improvement. Requires editor access to the scanner.
 */
export const VisionObservationsLabelCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionObservationsLabelCreateBodyFeedbackDefault = ``
export const visionObservationsLabelCreateBodyFeedbackMax = 5000

export const VisionObservationsLabelCreateBody = /* @__PURE__ */ zod
    .object({
        is_correct: zod.boolean().describe('True if the scanner scored this session correctly, false if not.'),
        feedback: zod
            .string()
            .max(visionObservationsLabelCreateBodyFeedbackMax)
            .default(visionObservationsLabelCreateBodyFeedbackDefault)
            .describe(
                'Optional written context on the rating, for thumbs-up and thumbs-down alike: what the scanner got right or wrong, or what it should have concluded.'
            ),
    })
    .describe("The team's shared judgement on whether the scanner scored this session correctly.")

/**
 * Remove the observation's shared label. Requires editor access to the scanner.
 */
export const VisionObservationsLabelDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const EnvironmentVisionQuotaRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionScannersListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod.string().optional().describe('Filter to scanners created by the given user IDs (comma-separated).'),
    emits_signals: zod.boolean().optional().describe('Filter to scanners that emit Signals.'),
    enabled: zod
        .string()
        .optional()
        .describe('Filter by enabled state. Accepts a comma-separated list of `enabled`\/`disabled`.'),
    experiment_id: zod.string().optional().describe('Filter to scanners whose targeting watches the given experiment.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .string()
        .optional()
        .describe(
            'Sort scanners by name, created_at, updated_at, scanner_type, enabled, sampling_rate, created_by, credits_this_month. Prefix with `-` for descending.'
        ),
    scanner_type: zod
        .string()
        .optional()
        .describe('Filter by scanner type (monitor, classifier, scorer, summarizer). Accepts a comma-separated list.'),
    search: zod
        .string()
        .optional()
        .describe('Case-insensitive substring match across name, description, and the prompt in scanner_config.'),
    tags: zod
        .string()
        .optional()
        .describe('Filter to scanners carrying at least one of the given tags (comma-separated).'),
})

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersCreateBodyNameMax = 255

export const visionScannersCreateBodyDescriptionMax = 1000

export const visionScannersCreateBodyTagsItemMax = 255

export const visionScannersCreateBodyTagsMax = 32

export const visionScannersCreateBodySamplingRateMin = 0
export const visionScannersCreateBodySamplingRateMax = 1

export const visionScannersCreateBodyCreditLimitMax = 2147483647

export const visionScannersCreateBodyExperimentTargetingOneVariantMax = 400

export const VisionScannersCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(visionScannersCreateBodyNameMax)
            .describe('Human-readable scanner name. Unique within the team.'),
        description: zod
            .string()
            .max(visionScannersCreateBodyDescriptionMax)
            .optional()
            .describe('Free-form description shown in the scanner management UI.'),
        tags: zod
            .array(zod.string().max(visionScannersCreateBodyTagsItemMax))
            .max(visionScannersCreateBodyTagsMax)
            .optional()
            .describe(
                "Organizational tags for this scanner. Distinct from a classifier's categories in scanner_config. Tags cannot contain commas."
            ),
        scanner_type: zod
            .enum(['monitor', 'classifier', 'scorer', 'summarizer'])
            .describe(
                '\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
            )
            .describe(
                'What the scanner does: monitor, classifier, scorer, or summarizer.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
            ),
        scanner_config: zod
            .unknown()
            .describe(
                'Type-specific configuration. All scanner types require `prompt`; monitors add optional `allow_inconclusive`, classifiers add `tags`, scorers add `scale`, summarizers add optional `length`.'
            ),
        query: zod
            .unknown()
            .optional()
            .describe(
                'Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`\/`date_to` are stripped on save — the schedule controls time, not the user.'
            ),
        sampling_rate: zod
            .number()
            .min(visionScannersCreateBodySamplingRateMin)
            .max(visionScannersCreateBodySamplingRateMax)
            .optional()
            .describe(
                '0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling). Use exactly 0 to pause scanning; non-zero rates below 0.0001 (0.01%) are rejected as below the sampling precision.'
            ),
        sampling_mode: zod
            .enum(['focused', 'balanced', 'comprehensive'])
            .describe('\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive')
            .optional()
            .describe(
                'Quality pre-filter applied before random sampling. focused = top sessions only, balanced = drops the lowest-quality, comprehensive = no filter (default).\n\n\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive'
            ),
        credit_limit: zod
            .number()
            .min(1)
            .max(visionScannersCreateBodyCreditLimitMax)
            .nullish()
            .describe(
                "Optional cap on this scanner's own credit spend per billing period. Null means no scanner-level cap. When reached, this scanner stops scanning until the period resets. It stays enabled and does not scan the sessions it skipped."
            ),
        provider: zod
            .enum(['google'])
            .describe('\* `google` - Google')
            .optional()
            .describe('LLM provider. v1 is Google-only.\n\n\* `google` - Google'),
        model: zod
            .enum(['gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-3.7-flash'])
            .describe(
                '\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.7-flash` - Gemini 3.7 Flash'
            )
            .describe(
                'Concrete model to use for this scanner.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.7-flash` - Gemini 3.7 Flash'
            ),
        enabled: zod
            .boolean()
            .optional()
            .describe(
                "When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work."
            ),
        emits_signals: zod
            .boolean()
            .optional()
            .describe(
                'When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals.'
            ),
        experiment_targeting: zod
            .union([
                zod
                    .object({
                        experiment_id: zod.number().min(1).describe('The experiment the scanner watches.'),
                        variant: zod
                            .string()
                            .max(visionScannersCreateBodyExperimentTargetingOneVariantMax)
                            .nullish()
                            .describe(
                                'Narrow to sessions of people exposed to this variant. Null means every variant.'
                            ),
                    })
                    .describe(
                        "The experiment a scanner watches. Scans derive their person-scoped exposure filter from\nthis blob at query time, so it is the only place an experiment can enter a scanner's\ntargeting — which is what lets the write-side access check and read-side redaction cover it."
                    ),
                zod.null(),
                zod.null(),
            ])
            .optional()
            .describe(
                "The experiment this scanner's targeting watches, if any. Set null when the experiment targeting is removed."
            ),
    })
    .describe('A Replay Vision scanner: its type, targeting query, and AI configuration.')

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersPartialUpdateBodyNameMax = 255

export const visionScannersPartialUpdateBodyDescriptionMax = 1000

export const visionScannersPartialUpdateBodyTagsItemMax = 255

export const visionScannersPartialUpdateBodyTagsMax = 32

export const visionScannersPartialUpdateBodySamplingRateMin = 0
export const visionScannersPartialUpdateBodySamplingRateMax = 1

export const visionScannersPartialUpdateBodyCreditLimitMax = 2147483647

export const visionScannersPartialUpdateBodyExperimentTargetingOneVariantMax = 400

export const VisionScannersPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(visionScannersPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable scanner name. Unique within the team.'),
        description: zod
            .string()
            .max(visionScannersPartialUpdateBodyDescriptionMax)
            .optional()
            .describe('Free-form description shown in the scanner management UI.'),
        tags: zod
            .array(zod.string().max(visionScannersPartialUpdateBodyTagsItemMax))
            .max(visionScannersPartialUpdateBodyTagsMax)
            .optional()
            .describe(
                "Organizational tags for this scanner. Distinct from a classifier's categories in scanner_config. Tags cannot contain commas."
            ),
        scanner_type: zod
            .enum(['monitor', 'classifier', 'scorer', 'summarizer'])
            .describe(
                '\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
            )
            .optional()
            .describe(
                'What the scanner does: monitor, classifier, scorer, or summarizer.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
            ),
        scanner_config: zod
            .unknown()
            .optional()
            .describe(
                'Type-specific configuration. All scanner types require `prompt`; monitors add optional `allow_inconclusive`, classifiers add `tags`, scorers add `scale`, summarizers add optional `length`.'
            ),
        query: zod
            .unknown()
            .optional()
            .describe(
                'Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`\/`date_to` are stripped on save — the schedule controls time, not the user.'
            ),
        sampling_rate: zod
            .number()
            .min(visionScannersPartialUpdateBodySamplingRateMin)
            .max(visionScannersPartialUpdateBodySamplingRateMax)
            .optional()
            .describe(
                '0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling). Use exactly 0 to pause scanning; non-zero rates below 0.0001 (0.01%) are rejected as below the sampling precision.'
            ),
        sampling_mode: zod
            .enum(['focused', 'balanced', 'comprehensive'])
            .describe('\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive')
            .optional()
            .describe(
                'Quality pre-filter applied before random sampling. focused = top sessions only, balanced = drops the lowest-quality, comprehensive = no filter (default).\n\n\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive'
            ),
        credit_limit: zod
            .number()
            .min(1)
            .max(visionScannersPartialUpdateBodyCreditLimitMax)
            .nullish()
            .describe(
                "Optional cap on this scanner's own credit spend per billing period. Null means no scanner-level cap. When reached, this scanner stops scanning until the period resets. It stays enabled and does not scan the sessions it skipped."
            ),
        provider: zod
            .enum(['google'])
            .describe('\* `google` - Google')
            .optional()
            .describe('LLM provider. v1 is Google-only.\n\n\* `google` - Google'),
        model: zod
            .enum(['gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-3.7-flash'])
            .describe(
                '\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.7-flash` - Gemini 3.7 Flash'
            )
            .optional()
            .describe(
                'Concrete model to use for this scanner.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.7-flash` - Gemini 3.7 Flash'
            ),
        enabled: zod
            .boolean()
            .optional()
            .describe(
                "When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work."
            ),
        emits_signals: zod
            .boolean()
            .optional()
            .describe(
                'When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals.'
            ),
        experiment_targeting: zod
            .union([
                zod
                    .object({
                        experiment_id: zod.number().min(1).describe('The experiment the scanner watches.'),
                        variant: zod
                            .string()
                            .max(visionScannersPartialUpdateBodyExperimentTargetingOneVariantMax)
                            .nullish()
                            .describe(
                                'Narrow to sessions of people exposed to this variant. Null means every variant.'
                            ),
                    })
                    .describe(
                        "The experiment a scanner watches. Scans derive their person-scoped exposure filter from\nthis blob at query time, so it is the only place an experiment can enter a scanner's\ntargeting — which is what lets the write-side access check and read-side redaction cover it."
                    ),
                zod.null(),
                zod.null(),
            ])
            .optional()
            .describe(
                "The experiment this scanner's targeting watches, if any. Set null when the experiment targeting is removed."
            ),
    })
    .describe('A Replay Vision scanner: its type, targeting query, and AI configuration.')

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Save the users this scanner matched as a static cohort, for surveys, funnels, and retention analysis.
 */
export const VisionScannersAffectedCohortCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersAffectedCohortCreateBodyWindowDaysDefault = 30
export const visionScannersAffectedCohortCreateBodyWindowDaysMax = 90

export const visionScannersAffectedCohortCreateBodyTagMax = 100

export const VisionScannersAffectedCohortCreateBody = /* @__PURE__ */ zod
    .object({
        window_days: zod
            .number()
            .min(1)
            .max(visionScannersAffectedCohortCreateBodyWindowDaysMax)
            .default(visionScannersAffectedCohortCreateBodyWindowDaysDefault)
            .describe('Trailing window of observations to count. Defaults to 30 days.'),
        tag: zod
            .string()
            .max(visionScannersAffectedCohortCreateBodyTagMax)
            .nullish()
            .describe(
                'Classifier scanners only, required for them: count sessions carrying this tag (fixed or freeform). Not applicable to other scanner types.'
            ),
        min_score: zod
            .number()
            .nullish()
            .describe(
                'Scorer scanners only: count sessions scoring at or above this value. Scorers require `min_score` and\/or `max_score`. Not applicable to other scanner types.'
            ),
        max_score: zod
            .number()
            .nullish()
            .describe('Scorer scanners only: count sessions scoring at or below this value.'),
    })
    .describe('Body of POST \/vision\/scanners\/:id\/affected_cohort\/. Same qualifiers as the impact GET.')

/**
 * Affected sessions and users for this scanner over the trailing window.
 */
export const VisionScannersImpactRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersImpactRetrieveQueryTagMax = 100

export const visionScannersImpactRetrieveQueryWindowDaysDefault = 30
export const visionScannersImpactRetrieveQueryWindowDaysMax = 90

export const VisionScannersImpactRetrieveQueryParams = /* @__PURE__ */ zod.object({
    max_score: zod.number().nullish().describe('Scorer scanners only: count sessions scoring at or below this value.'),
    min_score: zod
        .number()
        .nullish()
        .describe(
            'Scorer scanners only: count sessions scoring at or above this value. Scorers require `min_score` and\/or `max_score`. Not applicable to other scanner types.'
        ),
    tag: zod
        .string()
        .max(visionScannersImpactRetrieveQueryTagMax)
        .nullish()
        .describe(
            'Classifier scanners only, required for them: count sessions carrying this tag (fixed or freeform). Not applicable to other scanner types.'
        ),
    window_days: zod
        .number()
        .min(1)
        .max(visionScannersImpactRetrieveQueryWindowDaysMax)
        .default(visionScannersImpactRetrieveQueryWindowDaysDefault)
        .describe('Trailing window of observations to count. Defaults to 30 days.'),
})

/**
 * Apply this scanner to one specific session, on demand. Returns 202 with the workflow handle.
 */
export const VisionScannersObserveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersObserveCreateBodySessionIdMax = 128

export const VisionScannersObserveCreateBody = /* @__PURE__ */ zod
    .object({
        session_id: zod
            .string()
            .max(visionScannersObserveCreateBodySessionIdMax)
            .describe('ID of the session recording to apply the scanner to.'),
    })
    .describe('Body of POST \/vision\/scanners\/{id}\/observe\/.')

/**
 * Read-only access to observations produced by a scanner.
 */
export const VisionScannersObservationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersObservationsListQueryParams = /* @__PURE__ */ zod.object({
    backfill_id: zod.string().optional().describe('Only observations dispatched by this backfill.'),
    date_from: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or after this time. Accepts ISO 8601 or a relative date like `-7d`; values without an explicit offset are interpreted in the project's timezone."
        ),
    date_to: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or before this time. Accepts ISO 8601 or a relative date like `-1d`; date-only values include the whole day, interpreted in the project's timezone."
        ),
    labeled: zod
        .boolean()
        .optional()
        .describe(
            'When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.'
        ),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    max_score: zod
        .number()
        .optional()
        .describe(
            'Filter scorer observations to those scoring at or below this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.'
        ),
    min_score: zod
        .number()
        .optional()
        .describe(
            'Filter scorer observations to those scoring at or above this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.'
        ),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .string()
        .optional()
        .describe(
            'Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.'
        ),
    recording_subject: zod
        .string()
        .optional()
        .describe('Filter to observations whose person email contains this value (case-insensitive).'),
    session_id: zod
        .string()
        .optional()
        .describe('Filter to observations of one or more session recordings. Accepts a comma-separated list.'),
    status: zod.string().optional().describe('Filter by observation status. Accepts a comma-separated list.'),
    tags: zod
        .string()
        .optional()
        .describe(
            'Filter classifier observations whose fixed or freeform tags include any of the given values (comma-separated). Matches if the tag appears in either `tags` or `tags_freeform`.'
        ),
    triggered_by: zod
        .string()
        .optional()
        .describe(
            'Filter by trigger source (schedule, on_demand, retry, or backfill). Accepts a comma-separated list.'
        ),
    verdict: zod
        .string()
        .optional()
        .describe('Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).'),
})

/**
 * Retrieve one observation. Any list filters passed along (status, tags, order_by, …) scope the `previous_observation_id`/`next_observation_id` navigation to the matching, identically-ordered set — so prev/next from a filtered table stays within that filtered list.
 */
export const VisionScannersObservationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersObservationsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    backfill_id: zod.string().optional().describe('Only observations dispatched by this backfill.'),
    date_from: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or after this time. Accepts ISO 8601 or a relative date like `-7d`; values without an explicit offset are interpreted in the project's timezone."
        ),
    date_to: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or before this time. Accepts ISO 8601 or a relative date like `-1d`; date-only values include the whole day, interpreted in the project's timezone."
        ),
    labeled: zod
        .string()
        .optional()
        .describe(
            'When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.'
        ),
    max_score: zod
        .number()
        .optional()
        .describe(
            'Filter scorer observations to those scoring at or below this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.'
        ),
    min_score: zod
        .number()
        .optional()
        .describe(
            'Filter scorer observations to those scoring at or above this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.'
        ),
    order_by: zod
        .string()
        .optional()
        .describe(
            'Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), result_confidence, scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.'
        ),
    recording_subject: zod
        .string()
        .optional()
        .describe('Filter to observations whose person email contains this value (case-insensitive).'),
    session_id: zod
        .string()
        .optional()
        .describe('Filter to observations of one or more session recordings. Accepts a comma-separated list.'),
    status: zod.string().optional().describe('Filter by observation status. Accepts a comma-separated list.'),
    tags: zod
        .string()
        .optional()
        .describe(
            'Filter classifier observations whose fixed or freeform tags include any of the given values (comma-separated). Matches if the tag appears in either `tags` or `tags_freeform`.'
        ),
    triggered_by: zod
        .string()
        .optional()
        .describe(
            'Filter by trigger source (schedule, on_demand, retry, or backfill). Accepts a comma-separated list.'
        ),
    verdict: zod
        .string()
        .optional()
        .describe('Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).'),
})

/**
 * Aggregate counts and per-scanner-type distributions over the filtered observation set. Same filters as the list endpoint apply.
 */
export const VisionScannersObservationsStatsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersObservationsStatsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    backfill_id: zod.string().optional().describe('Only observations dispatched by this backfill.'),
    date_from: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or after this time. Accepts ISO 8601 or a relative date like `-7d`; values without an explicit offset are interpreted in the project's timezone."
        ),
    date_to: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or before this time. Accepts ISO 8601 or a relative date like `-1d`; date-only values include the whole day, interpreted in the project's timezone."
        ),
    labeled: zod
        .string()
        .optional()
        .describe(
            'When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.'
        ),
    max_score: zod
        .number()
        .optional()
        .describe(
            'Filter scorer observations to those scoring at or below this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.'
        ),
    min_score: zod
        .number()
        .optional()
        .describe(
            'Filter scorer observations to those scoring at or above this value. Rows with no numeric score (other scanner types, failed or in-flight runs) are excluded.'
        ),
    recent_days: zod
        .number()
        .optional()
        .describe(
            'Window size in days for the coverage `recent_sessions` count. Clamped to [1, 365]. Defaults to 14 when omitted.'
        ),
    recording_subject: zod
        .string()
        .optional()
        .describe('Filter to observations whose person email contains this value (case-insensitive).'),
    session_id: zod
        .string()
        .optional()
        .describe('Filter to observations of one or more session recordings. Accepts a comma-separated list.'),
    status: zod.string().optional().describe('Filter by observation status. Accepts a comma-separated list.'),
    tags: zod
        .string()
        .optional()
        .describe(
            'Filter classifier observations whose fixed or freeform tags include any of the given values (comma-separated). Matches if the tag appears in either `tags` or `tags_freeform`.'
        ),
    triggered_by: zod
        .string()
        .optional()
        .describe(
            'Filter by trigger source (schedule, on_demand, retry, or backfill). Accepts a comma-separated list.'
        ),
    verdict: zod
        .string()
        .optional()
        .describe('Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).'),
})

/**
 * Apply this suggestion: write a config to the scanner (the prompt plus any type-specific config such as classifier tags or the monitor allow_inconclusive flag), bumping the scanner version, and mark the suggestion applied. Pass `config` to apply an edited subset of the recommendation; omit it to apply the full suggested config. Only the current pending suggestion can be applied. Requires session recording edit access.
 */
export const VisionScannersPromptSuggestionsApplyCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner prompt suggestion.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersPromptSuggestionsApplyCreateBody = /* @__PURE__ */ zod.object({
    config: zod
        .unknown()
        .optional()
        .describe(
            "The edited config to apply, assembled from the recommendation's approved fields. Omit to apply the full suggested config unchanged."
        ),
})

/**
 * Dismiss this suggestion without applying it. Only the current pending suggestion can be dismissed. Requires editor access to the scanner.
 */
export const VisionScannersPromptSuggestionsDismissCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner prompt suggestion.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

/**
 * The scanner's newest prompt suggestion plus whether it is stale (the ratings changed since it was generated) and how many rated observations are available.
 */
export const VisionScannersPromptSuggestionsCurrentRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

/**
 * Generate a fresh prompt suggestion from the team's current ratings. The previous pending suggestion becomes history (superseded). Requires at least one rated observation and editor access to the scanner.
 */
export const VisionScannersPromptSuggestionsGenerateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

/**
 * Estimate the observation volume a proposed scanner would generate, for the pre-save cost preview.
 */
export const VisionScannersEstimateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersEstimateCreateBodySamplingRateDefault = 1
export const visionScannersEstimateCreateBodySamplingRateMin = 0
export const visionScannersEstimateCreateBodySamplingRateMax = 1

export const visionScannersEstimateCreateBodySamplingModeDefault = `comprehensive`
export const visionScannersEstimateCreateBodyModelDefault = `gemini-3-flash-preview`
export const visionScannersEstimateCreateBodyExperimentTargetingOneVariantMax = 400

export const VisionScannersEstimateCreateBody = /* @__PURE__ */ zod
    .object({
        query: zod
            .unknown()
            .optional()
            .describe(
                'Proposed `RecordingsQuery` for the candidate filter. `date_from`\/`date_to` are ignored — the estimate always uses a fixed 30-day lookback. Omit to estimate against all recordings.'
            ),
        sampling_rate: zod
            .number()
            .min(visionScannersEstimateCreateBodySamplingRateMin)
            .max(visionScannersEstimateCreateBodySamplingRateMax)
            .default(visionScannersEstimateCreateBodySamplingRateDefault)
            .describe('0..1 downsample applied to matched sessions. Defaults to 1.0 (no downsampling).'),
        sampling_mode: zod
            .enum(['focused', 'balanced', 'comprehensive'])
            .describe('\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive')
            .default(visionScannersEstimateCreateBodySamplingModeDefault)
            .describe(
                "Quality pre-filter applied to the matched-session count, mirroring the sweep's candidate query. Defaults to comprehensive (no filter).\n\n\* `focused` - Focused\n\* `balanced` - Balanced\n\* `comprehensive` - Comprehensive"
            ),
        scanner_id: zod
            .string()
            .nullish()
            .describe(
                "The scanner being edited, excluded from `other_enabled_scanners_monthly_credits` so its stored estimate isn't double-counted in the forecast. Omit (or null) when estimating a brand-new scanner."
            ),
        model: zod
            .enum(['gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-3.7-flash'])
            .describe(
                '\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.7-flash` - Gemini 3.7 Flash'
            )
            .default(visionScannersEstimateCreateBodyModelDefault)
            .describe(
                'Proposed model; determines `credits_per_observation` in the response.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.7-flash` - Gemini 3.7 Flash'
            ),
        experiment_targeting: zod
            .union([
                zod
                    .object({
                        experiment_id: zod.number().min(1).describe('The experiment the scanner watches.'),
                        variant: zod
                            .string()
                            .max(visionScannersEstimateCreateBodyExperimentTargetingOneVariantMax)
                            .nullish()
                            .describe(
                                'Narrow to sessions of people exposed to this variant. Null means every variant.'
                            ),
                    })
                    .describe(
                        "The experiment a scanner watches. Scans derive their person-scoped exposure filter from\nthis blob at query time, so it is the only place an experiment can enter a scanner's\ntargeting — which is what lets the write-side access check and read-side redaction cover it."
                    ),
                zod.null(),
                zod.null(),
            ])
            .optional()
            .describe(
                'Proposed experiment targeting, merged into the query as its exposure filter the same way a saved scanner derives it. The estimate then runs as the requesting user.'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/estimate\/ — a proposed, unsaved scanner config.')

/**
 * Scan named sessions against a prompt without saving a scanner first, for one-off questions.
 *
 * The config resolves to a scanner minted on first use, so asking the same question twice reuses
 * the observations it already has, while a different question about the same session gets its own.
 */
export const VisionScannersInlineScanCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersInlineScanCreateBodySessionIdsItemMax = 128

export const visionScannersInlineScanCreateBodySessionIdsMax = 200

export const visionScannersInlineScanCreateBodyPromptMax = 20000

export const visionScannersInlineScanCreateBodyScannerTypeDefault = `monitor`
export const visionScannersInlineScanCreateBodyModelDefault = `gemini-3-flash-preview`

export const VisionScannersInlineScanCreateBody = /* @__PURE__ */ zod
    .object({
        session_ids: zod
            .array(zod.string().max(visionScannersInlineScanCreateBodySessionIdsItemMax))
            .max(visionScannersInlineScanCreateBodySessionIdsMax)
            .describe(
                'Session recording IDs to scan, at most 200 per request. Scans start until the in-flight limit or monthly credit quota is reached; the rest are reported as skipped rather than failing the whole batch.'
            ),
        prompt: zod
            .string()
            .max(visionScannersInlineScanCreateBodyPromptMax)
            .describe(
                'What to look for in these sessions, in plain language. The same instruction a saved scanner carries.'
            ),
        scanner_type: zod
            .enum(['monitor', 'classifier', 'scorer', 'summarizer'])
            .describe(
                '\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
            )
            .default(visionScannersInlineScanCreateBodyScannerTypeDefault)
            .describe(
                'What the scan produces. Defaults to monitor, an open-ended observation against the prompt.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
            ),
        scanner_config: zod
            .unknown()
            .optional()
            .describe(
                'Type-specific configuration beyond the prompt: `tags` for a classifier, `scale` for a scorer, optional `length` for a summarizer. Omit it for a monitor. `prompt` belongs in the `prompt` field and is rejected here.'
            ),
        model: zod
            .enum(['gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-3.7-flash'])
            .describe(
                '\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.7-flash` - Gemini 3.7 Flash'
            )
            .default(visionScannersInlineScanCreateBodyModelDefault)
            .describe(
                'Model to scan with. Determines what each observation costs in credits.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.7-flash` - Gemini 3.7 Flash'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/inline_scan\/ - a prompt plus the sessions to point it at.')
