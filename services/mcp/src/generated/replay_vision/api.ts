/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 52 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const VisionAlertsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionAlertsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    scanner_id: zod.string().optional().describe('Only return alerts on this scanner.'),
})

export const VisionAlertsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionAlertsCreateBodyNameDefault = `Untitled alert`
export const visionAlertsCreateBodyNameMax = 255

export const visionAlertsCreateBodyEnabledDefault = true
export const visionAlertsCreateBodySelectionOneVerdictItemMax = 100

export const visionAlertsCreateBodySelectionOneVerdictMax = 10

export const visionAlertsCreateBodySelectionOneTagsItemMax = 200

export const visionAlertsCreateBodySelectionOneTagsMax = 20

export const visionAlertsCreateBodyCheckIntervalMinutesMin = 15

export const visionAlertsCreateBodyEvaluationPeriodsMax = 10

export const visionAlertsCreateBodyDatapointsToAlarmMax = 10

export const visionAlertsCreateBodyCooldownMinutesMin = 0

export const VisionAlertsCreateBody = () => zod.object({
    scanner_id: zod.string().describe('Scanner whose observations this alert watches. Immutable after creation.'),
    name: zod
        .string()
        .max(visionAlertsCreateBodyNameMax)
        .default(visionAlertsCreateBodyNameDefault)
        .describe("Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted."),
    enabled: zod
        .boolean()
        .default(visionAlertsCreateBodyEnabledDefault)
        .describe('Whether the alert is active. Disabling a metric alert resets its state to not_firing.'),
    kind: zod
        .enum(['metric', 'match'])
        .describe('\* `metric` - Metric\n\* `match` - Match')
        .describe(
            "'metric' fires when a metric crosses a threshold over a rolling window; 'match' fires on every observation that matches the selection. Immutable after creation.\n\n\* `metric` - Metric\n\* `match` - Match"
        ),
    selection: zod
        .object({
            verdict: zod
                .array(zod.string().max(visionAlertsCreateBodySelectionOneVerdictItemMax))
                .max(visionAlertsCreateBodySelectionOneVerdictMax)
                .optional()
                .describe("Monitor verdicts to match, e.g. ['yes']."),
            tags: zod
                .array(zod.string().max(visionAlertsCreateBodySelectionOneTagsItemMax))
                .max(visionAlertsCreateBodySelectionOneTagsMax)
                .optional()
                .describe('Classifier tags to match; an observation matches when it carries any of them.'),
            min_score: zod.number().optional().describe('Minimum scorer score (inclusive).'),
            max_score: zod.number().optional().describe('Maximum scorer score (inclusive).'),
        })
        .optional()
        .describe('Which observations count. Empty matches every observation of the scanner.'),
    metric: zod
        .enum(['count', 'avg_score'])
        .describe('\* `count` - Count matching observations\n\* `avg_score` - Average score')
        .optional()
        .describe(
            "Metric alerts only: what to measure over the window. 'avg_score' requires a scorer scanner.\n\n\* `count` - Count matching observations\n\* `avg_score` - Average score"
        ),
    direction: zod
        .enum(['above', 'below'])
        .describe('\* `above` - At or above\n\* `below` - At or below')
        .optional()
        .describe(
            'Metric alerts only: whether the alert fires at or above, or at or below, the threshold.\n\n\* `above` - At or above\n\* `below` - At or below'
        ),
    threshold: zod
        .number()
        .nullish()
        .describe(
            'Metric alerts only: the threshold value. Required for metric alerts, must be omitted for match alerts.'
        ),
    window_days: zod
        .number()
        .optional()
        .describe('Metric alerts only: rolling window in days. Allowed values: [1, 3, 7, 14, 30].'),
    check_interval_minutes: zod
        .number()
        .min(visionAlertsCreateBodyCheckIntervalMinutesMin)
        .optional()
        .describe('Metric alerts only: evaluation cadence in minutes, at least 15.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(visionAlertsCreateBodyEvaluationPeriodsMax)
        .optional()
        .describe('Metric alerts only: total check periods in the sliding evaluation window (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(visionAlertsCreateBodyDatapointsToAlarmMax)
        .optional()
        .describe('Metric alerts only: how many periods must breach to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(visionAlertsCreateBodyCooldownMinutesMin)
        .optional()
        .describe('Metric alerts only: minimum minutes between repeated notifications. 0 means no cooldown.'),
    schedule_restriction: zod
        .union([
            zod.object({
                blocked_windows: zod
                    .array(
                        zod.object({
                            start: zod
                                .string()
                                .describe(
                                    'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                ),
                            end: zod
                                .string()
                                .describe(
                                    'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                ),
                        })
                    )
                    .describe(
                        'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                    ),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Blocked local time windows when the alert must not notify. Times use the project timezone. Null disables quiet hours.'
        ),
    snooze_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.'),
})

export const VisionAlertsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this vision alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionAlertsPartialUpdateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this vision alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionAlertsPartialUpdateBodyNameMax = 255

export const visionAlertsPartialUpdateBodySelectionOneVerdictItemMax = 100

export const visionAlertsPartialUpdateBodySelectionOneVerdictMax = 10

export const visionAlertsPartialUpdateBodySelectionOneTagsItemMax = 200

export const visionAlertsPartialUpdateBodySelectionOneTagsMax = 20

export const visionAlertsPartialUpdateBodyCheckIntervalMinutesMin = 15

export const visionAlertsPartialUpdateBodyEvaluationPeriodsMax = 10

export const visionAlertsPartialUpdateBodyDatapointsToAlarmMax = 10

export const visionAlertsPartialUpdateBodyCooldownMinutesMin = 0

export const VisionAlertsPartialUpdateBody = () => zod.object({
    scanner_id: zod
        .string()
        .optional()
        .describe('Scanner whose observations this alert watches. Immutable after creation.'),
    name: zod
        .string()
        .max(visionAlertsPartialUpdateBodyNameMax)
        .optional()
        .describe("Human-readable name for this alert. Defaults to 'Untitled alert' on create when omitted."),
    enabled: zod
        .boolean()
        .optional()
        .describe('Whether the alert is active. Disabling a metric alert resets its state to not_firing.'),
    kind: zod
        .enum(['metric', 'match'])
        .describe('\* `metric` - Metric\n\* `match` - Match')
        .optional()
        .describe(
            "'metric' fires when a metric crosses a threshold over a rolling window; 'match' fires on every observation that matches the selection. Immutable after creation.\n\n\* `metric` - Metric\n\* `match` - Match"
        ),
    selection: zod
        .object({
            verdict: zod
                .array(zod.string().max(visionAlertsPartialUpdateBodySelectionOneVerdictItemMax))
                .max(visionAlertsPartialUpdateBodySelectionOneVerdictMax)
                .optional()
                .describe("Monitor verdicts to match, e.g. ['yes']."),
            tags: zod
                .array(zod.string().max(visionAlertsPartialUpdateBodySelectionOneTagsItemMax))
                .max(visionAlertsPartialUpdateBodySelectionOneTagsMax)
                .optional()
                .describe('Classifier tags to match; an observation matches when it carries any of them.'),
            min_score: zod.number().optional().describe('Minimum scorer score (inclusive).'),
            max_score: zod.number().optional().describe('Maximum scorer score (inclusive).'),
        })
        .optional()
        .describe('Which observations count. Empty matches every observation of the scanner.'),
    metric: zod
        .enum(['count', 'avg_score'])
        .describe('\* `count` - Count matching observations\n\* `avg_score` - Average score')
        .optional()
        .describe(
            "Metric alerts only: what to measure over the window. 'avg_score' requires a scorer scanner.\n\n\* `count` - Count matching observations\n\* `avg_score` - Average score"
        ),
    direction: zod
        .enum(['above', 'below'])
        .describe('\* `above` - At or above\n\* `below` - At or below')
        .optional()
        .describe(
            'Metric alerts only: whether the alert fires at or above, or at or below, the threshold.\n\n\* `above` - At or above\n\* `below` - At or below'
        ),
    threshold: zod
        .number()
        .nullish()
        .describe(
            'Metric alerts only: the threshold value. Required for metric alerts, must be omitted for match alerts.'
        ),
    window_days: zod
        .number()
        .optional()
        .describe('Metric alerts only: rolling window in days. Allowed values: [1, 3, 7, 14, 30].'),
    check_interval_minutes: zod
        .number()
        .min(visionAlertsPartialUpdateBodyCheckIntervalMinutesMin)
        .optional()
        .describe('Metric alerts only: evaluation cadence in minutes, at least 15.'),
    evaluation_periods: zod
        .number()
        .min(1)
        .max(visionAlertsPartialUpdateBodyEvaluationPeriodsMax)
        .optional()
        .describe('Metric alerts only: total check periods in the sliding evaluation window (M in N-of-M).'),
    datapoints_to_alarm: zod
        .number()
        .min(1)
        .max(visionAlertsPartialUpdateBodyDatapointsToAlarmMax)
        .optional()
        .describe('Metric alerts only: how many periods must breach to fire (N in N-of-M).'),
    cooldown_minutes: zod
        .number()
        .min(visionAlertsPartialUpdateBodyCooldownMinutesMin)
        .optional()
        .describe('Metric alerts only: minimum minutes between repeated notifications. 0 means no cooldown.'),
    schedule_restriction: zod
        .union([
            zod.object({
                blocked_windows: zod
                    .array(
                        zod.object({
                            start: zod
                                .string()
                                .describe(
                                    'Start time HH:MM (24-hour, project timezone). Inclusive. Each window must span ≥ 30 minutes on the local daily timeline (half-open [start, end)).'
                                ),
                            end: zod
                                .string()
                                .describe(
                                    'End time HH:MM (24-hour). Exclusive (half-open interval). Each window must span ≥ 30 minutes locally.'
                                ),
                        })
                    )
                    .describe(
                        'Blocked local time windows when the alert must not run. Overlapping or identical windows are merged when saved. At most five windows before normalization; empty array clears quiet hours.'
                    ),
            }),
            zod.null(),
        ])
        .optional()
        .describe(
            'Blocked local time windows when the alert must not notify. Times use the project timezone. Null disables quiet hours.'
        ),
    snooze_until: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe('ISO 8601 timestamp until which the alert is snoozed. Set to null to unsnooze.'),
})

export const VisionAlertsDestroyParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this vision alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Create a notification destination for this alert. One HogFunction is created per alert event kind atomically.
 */
export const VisionAlertsDestinationsCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this vision alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionAlertsDestinationsCreateBody = () => zod.object({
    type: zod
        .enum(['slack', 'webhook'])
        .describe('\* `slack` - slack\n\* `webhook` - webhook')
        .describe('Notification destination type.\n\n\* `slack` - slack\n\* `webhook` - webhook'),
    slack_workspace_id: zod
        .number()
        .optional()
        .describe('Integration ID for the Slack workspace. Required when type=slack.'),
    slack_channel_id: zod.string().optional().describe('Slack channel ID. Required when type=slack.'),
    slack_channel_name: zod.string().optional().describe('Human-readable channel name for display.'),
    webhook_url: zod.url().optional().describe('HTTPS endpoint to post to. Required when type=webhook.'),
})

/**
 * Delete a notification destination by deleting its HogFunction group atomically.
 */
export const VisionAlertsDestinationsDeleteCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this vision alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionAlertsDestinationsDeleteCreateBodyHogFunctionIdsMax = 5

export const VisionAlertsDestinationsDeleteCreateBody = () => zod.object({
    hog_function_ids: zod
        .array(zod.string())
        .min(1)
        .max(visionAlertsDestinationsDeleteCreateBodyHogFunctionIdsMax)
        .describe('HogFunction IDs to delete as one atomic destination group.'),
})

/**
 * Paginated event history for this alert, newest first. Quiet no-op check rows (no state change, no error) are filtered out. Optional `?kind=...` narrows to one kind.
 */
export const VisionAlertsEventsListParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this vision alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionAlertsEventsListQueryParams = () => zod.object({
    kind: zod
        .enum(['check', 'disable', 'enable', 'reset', 'snooze', 'threshold_change', 'unsnooze'])
        .optional()
        .describe('Narrow the history to one event kind.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Reset a broken alert. Clears the consecutive-failure counter and schedules an immediate recheck.
 */
export const VisionAlertsResetCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this vision alert configuration.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * A session's observations across every scanner the caller can read, plus the team-level semantic
 * `search` action, which resolves its own scanner scope instead of this queryset.
 */
export const VisionObservationsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionObservationsListQueryParams = () => zod.object({
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
export const VisionObservationsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionObservationsRetrieveQueryParams = () => zod.object({
    backfill_id: zod.string().optional().describe('Only observations dispatched by this backfill.'),
    date_from: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or after this time. Accepts ISO 8601, a relative date like `-7d`, or `now`; values without an explicit offset are interpreted in the project's timezone."
        ),
    date_to: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or before this time. Accepts ISO 8601, a relative date like `-1d`, or `now` for the current time; omit it to query through the current time. Date-only values include the whole day, interpreted in the project's timezone."
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
 * Create a PostHog Task from this observation's finding so it can be triaged and fixed. Title and description are derived from the scanner and its result. Record-only: this does not start the coding agent. Idempotent per observation: once a task exists, repeat calls return its id with a 200 instead of creating a duplicate.
 */
export const VisionObservationsCreateTaskCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Set or update the observation's shared label: whether the scanner scored the session correctly, plus optional feedback on what it got wrong. One label per observation, shared across the team; these labels feed prompt improvement. Requires editor access to the scanner.
 */
export const VisionObservationsLabelCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionObservationsLabelCreateBodyFeedbackDefault = ``
export const visionObservationsLabelCreateBodyFeedbackMax = 5000

export const VisionObservationsLabelCreateBody = () => zod
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
export const VisionObservationsLabelDestroyParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Delete a failed or ineligible observation and re-run its scanner on the same recording. Returns 202 with the workflow handle.
 */
export const VisionObservationsRetryCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * The inbox reports this observation's emitted signals were grouped into, newest first.
 */
export const VisionObservationsSignalReportsListParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Rank observations by semantic similarity to the search text, optionally filtered by exact outcome
 * (verdict, score, tags).
 */
export const VisionObservationsSearchRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionObservationsSearchRetrieveQueryLimitDefault = 20
export const visionObservationsSearchRetrieveQueryLimitMax = 50

export const visionObservationsSearchRetrieveQueryQMax = 2000

export const VisionObservationsSearchRetrieveQueryParams = () => zod.object({
    date_from: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Only observations analyzed at or after this time. Accepts ISO 8601, a relative date like `-7d`, or `now`; values without an explicit offset are interpreted in the project's timezone."
        ),
    date_to: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Only observations analyzed at or before this time. Accepts ISO 8601, a relative date like `-1d`, or `now` for the current time; omit it to query through the current time. Date-only values include the whole day, interpreted in the project's timezone."
        ),
    limit: zod
        .number()
        .min(1)
        .max(visionObservationsSearchRetrieveQueryLimitMax)
        .default(visionObservationsSearchRetrieveQueryLimitDefault)
        .describe('Maximum number of results (default 20, at most 50).'),
    max_score: zod.number().optional().describe('Keep only scorer observations with a score at or below this value.'),
    min_score: zod.number().optional().describe('Keep only scorer observations with a score at or above this value.'),
    q: zod
        .string()
        .min(1)
        .max(visionObservationsSearchRetrieveQueryQMax)
        .describe("Natural-language description of what to find, e.g. 'users confused by the pricing page'."),
    scanner_id: zod
        .string()
        .optional()
        .describe("Search a single scanner's observations. Defaults to every scanner you can read."),
    tags: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'Comma-separated classifier tags to keep. Matching is case- and format-insensitive. Unlike `verdict`, tags are not validated against a fixed list, so an unknown tag matches nothing.'
        ),
    verdict: zod
        .string()
        .min(1)
        .optional()
        .describe('Comma-separated monitor verdicts to keep, e.g. `yes,inconclusive`.'),
})

export const EnvironmentVisionQuotaRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const EnvironmentVisionQuotaSpendSeriesRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const VisionScannersListQueryParams = () => zod.object({
    created_by: zod.string().optional().describe('Filter to scanners created by the given user IDs (comma-separated).'),
    emits_signals: zod.boolean().optional().describe('Filter to scanners that emit Signals.'),
    enabled: zod
        .string()
        .optional()
        .describe(
            'Filter by enabled state. Accepts `enabled`, `disabled`, a comma-separated list of both, or the boolean form `true`\/`false`. Omit to list every scanner.'
        ),
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
export const VisionScannersCreateParams = () => zod.object({
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

export const VisionScannersCreateBody = () => zod
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
        creation_method: zod
            .union([
                zod
                    .enum(['ai', 'template', 'scratch'])
                    .describe('\* `ai` - AI draft\n\* `template` - Template\n\* `scratch` - From scratch'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How the creator built this scanner: from an AI draft, from a template, or from scratch. Reported to product analytics at creation and not stored on the scanner. Independent of any experiment the creator is in, since a person offered the AI flow can still fill the form by hand. Only the app can answer this, so a request from anywhere else reports the calling surface instead of whatever it sends here. Ignored on update.\n\n\* `ai` - AI draft\n\* `template` - Template\n\* `scratch` - From scratch'
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
            .enum(['gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-3.8-flash'])
            .describe(
                '\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.8-flash` - Gemini 3.8 Flash'
            )
            .describe(
                'Concrete model to use for this scanner.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.8-flash` - Gemini 3.8 Flash'
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
export const VisionScannersRetrieveParams = () => zod.object({
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
export const VisionScannersPartialUpdateParams = () => zod.object({
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

export const VisionScannersPartialUpdateBody = () => zod
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
        creation_method: zod
            .union([
                zod
                    .enum(['ai', 'template', 'scratch'])
                    .describe('\* `ai` - AI draft\n\* `template` - Template\n\* `scratch` - From scratch'),
                zod.null(),
            ])
            .optional()
            .describe(
                'How the creator built this scanner: from an AI draft, from a template, or from scratch. Reported to product analytics at creation and not stored on the scanner. Independent of any experiment the creator is in, since a person offered the AI flow can still fill the form by hand. Only the app can answer this, so a request from anywhere else reports the calling surface instead of whatever it sends here. Ignored on update.\n\n\* `ai` - AI draft\n\* `template` - Template\n\* `scratch` - From scratch'
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
            .enum(['gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-3.8-flash'])
            .describe(
                '\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.8-flash` - Gemini 3.8 Flash'
            )
            .optional()
            .describe(
                'Concrete model to use for this scanner.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.8-flash` - Gemini 3.8 Flash'
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
export const VisionScannersDestroyParams = () => zod.object({
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
export const VisionScannersAffectedCohortCreateParams = () => zod.object({
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

export const VisionScannersAffectedCohortCreateBody = () => zod
    .object({
        window_days: zod
            .number()
            .min(1)
            .max(visionScannersAffectedCohortCreateBodyWindowDaysMax)
            .default(visionScannersAffectedCohortCreateBodyWindowDaysDefault)
            .describe('Trailing window of observations to count. Defaults to 30 days.'),
        verdict: zod
            .union([
                zod
                    .enum(['yes', 'no', 'inconclusive'])
                    .describe('\* `yes` - Yes\n\* `no` - No\n\* `inconclusive` - Inconclusive'),
                zod.null(),
            ])
            .optional()
            .describe(
                'Monitor scanners only: count sessions with this verdict. Defaults to `yes`. Not applicable to other scanner types.\n\n\* `yes` - Yes\n\* `no` - No\n\* `inconclusive` - Inconclusive'
            ),
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
 * Apply this scanner to many sessions on demand. Starts as many as fit under the in-flight
 * caps and monthly credit quota, reporting the rest as skipped rather than failing the batch.
 */
export const VisionScannersBulkObserveCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersBulkObserveCreateBodySessionIdsItemMax = 128

export const visionScannersBulkObserveCreateBodySessionIdsMax = 200

export const VisionScannersBulkObserveCreateBody = () => zod
    .object({
        session_ids: zod
            .array(zod.string().max(visionScannersBulkObserveCreateBodySessionIdsItemMax))
            .max(visionScannersBulkObserveCreateBodySessionIdsMax)
            .describe(
                'Session recording IDs to scan on demand, at most 200 per request. Scans start until the in-flight limit or monthly credit quota is reached; the rest are reported as skipped rather than failing the whole batch. Already-running sessions are a no-op.'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/{id}\/bulk_observe\/.')

/**
 * Copy a scanner into a new disabled scanner named "<name> (copy)".
 *
 * Copies the stored model row rather than the serializer's read representation, so a query
 * that no longer validates survives the copy; duplicating through the create endpoint would
 * silently drop it. Experiment targeting is the exception and follows the read path instead.
 * Unlike create, no digest is provisioned: the copy starts disabled and unreviewed.
 */
export const VisionScannersDuplicateCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Affected sessions and users for this scanner over the trailing window.
 */
export const VisionScannersImpactRetrieveParams = () => zod.object({
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

export const VisionScannersImpactRetrieveQueryParams = () => zod.object({
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
    verdict: zod
        .union([zod.literal('yes'), zod.literal('no'), zod.literal('inconclusive'), zod.literal(null)])
        .nullish()
        .describe(
            'Monitor scanners only: count sessions with this verdict. Defaults to `yes`. Not applicable to other scanner types.\n\n\* `yes` - Yes\n\* `no` - No\n\* `inconclusive` - Inconclusive'
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
export const VisionScannersObserveCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersObserveCreateBodySessionIdMax = 128

export const VisionScannersObserveCreateBody = () => zod
    .object({
        session_id: zod
            .string()
            .max(visionScannersObserveCreateBodySessionIdMax)
            .describe('ID of the session recording to apply the scanner to.'),
    })
    .describe('Body of POST \/vision\/scanners\/{id}\/observe\/.')

/**
 * What self-driving did with this scanner's signals: reports contributed to and PRs opened.
 */
export const VisionScannersSelfDrivingStatsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Historical backfills of a scanner over a closed time window (nested under a scanner).
 */
export const VisionScannersBackfillsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersBackfillsListQueryParams = () => zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Create a backfill: freeze the scanner config, enumerate the exact candidate set, start the tick schedule.
 *
 * The enumeration reruns here rather than trusting the client-confirmed estimate: the count is
 * billing-relevant, so the authoritative value is computed server-side at creation time. New
 * settled sessions between estimate and confirm can nudge total_count slightly.
 */
export const VisionScannersBackfillsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const visionScannersBackfillsCreateBodyMaxTotalCreditsMin = 0

export const VisionScannersBackfillsCreateBody = () => zod.object({
    window_start: zod.iso
        .datetime({ offset: true })
        .describe('Inclusive lower bound of the historical window to scan.'),
    window_end: zod.iso
        .datetime({ offset: true })
        .describe('Exclusive upper bound of the window; clamped server-side to now.'),
    max_total_credits: zod
        .number()
        .min(visionScannersBackfillsCreateBodyMaxTotalCreditsMin)
        .describe(
            'The most this backfill may cost, in credits (1 credit = $0.01): pass the `total_credits` from the estimate the person agreed to. The create is rejected if the window now costs more.'
        ),
})

/**
 * Historical backfills of a scanner over a closed time window (nested under a scanner).
 */
export const VisionScannersBackfillsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner backfill.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

/**
 * Stop an active backfill; already-dispatched observations finish, nothing new dispatches.
 */
export const VisionScannersBackfillsCancelCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner backfill.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersBackfillsCancelCreateBody = () => zod.looseObject({})

/**
 * Restart a backfill that paused when the monthly quota ran out.
 */
export const VisionScannersBackfillsResumeCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner backfill.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersBackfillsResumeCreateBody = () => zod.looseObject({})

/**
 * Exactly enumerate what a backfill over the given window would dispatch and cost.
 */
export const VisionScannersBackfillsEstimateCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersBackfillsEstimateCreateBody = () => zod.object({
    window_start: zod.iso
        .datetime({ offset: true })
        .describe('Inclusive lower bound of the historical window to scan.'),
    window_end: zod.iso
        .datetime({ offset: true })
        .describe('Exclusive upper bound of the window; clamped server-side to now.'),
})

/**
 * Read-only access to observations produced by a scanner.
 */
export const VisionScannersObservationsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersObservationsListQueryParams = () => zod.object({
    backfill_id: zod.string().optional().describe('Only observations dispatched by this backfill.'),
    date_from: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or after this time. Accepts ISO 8601, a relative date like `-7d`, or `now`; values without an explicit offset are interpreted in the project's timezone."
        ),
    date_to: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or before this time. Accepts ISO 8601, a relative date like `-1d`, or `now` for the current time; omit it to query through the current time. Date-only values include the whole day, interpreted in the project's timezone."
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
export const VisionScannersObservationsRetrieveParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersObservationsRetrieveQueryParams = () => zod.object({
    backfill_id: zod.string().optional().describe('Only observations dispatched by this backfill.'),
    date_from: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or after this time. Accepts ISO 8601, a relative date like `-7d`, or `now`; values without an explicit offset are interpreted in the project's timezone."
        ),
    date_to: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or before this time. Accepts ISO 8601, a relative date like `-1d`, or `now` for the current time; omit it to query through the current time. Date-only values include the whole day, interpreted in the project's timezone."
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
export const VisionScannersObservationsStatsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersObservationsStatsRetrieveQueryParams = () => zod.object({
    backfill_id: zod.string().optional().describe('Only observations dispatched by this backfill.'),
    date_from: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or after this time. Accepts ISO 8601, a relative date like `-7d`, or `now`; values without an explicit offset are interpreted in the project's timezone."
        ),
    date_to: zod
        .string()
        .optional()
        .describe(
            "Only observations created at or before this time. Accepts ISO 8601, a relative date like `-1d`, or `now` for the current time; omit it to query through the current time. Date-only values include the whole day, interpreted in the project's timezone."
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
export const VisionScannersPromptSuggestionsApplyCreateParams = () => zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner prompt suggestion.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersPromptSuggestionsApplyCreateBody = () => zod.object({
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
export const VisionScannersPromptSuggestionsDismissCreateParams = () => zod.object({
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
export const VisionScannersPromptSuggestionsCurrentRetrieveParams = () => zod.object({
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
export const VisionScannersPromptSuggestionsGenerateCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

/**
 * Reports filed by this scanner's scouts, newest first.
 */
export const VisionScannersScoutReportsListParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

/**
 * One report filed by this scanner's scouts.
 */
export const VisionScannersScoutReportsRetrieveParams = () => zod.object({
    id: zod.string(),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

/**
 * Create a scout that watches this scanner, recorded as belonging to it.
 */
export const VisionScannersScoutsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
    scanner_id: zod.string(),
})

export const visionScannersScoutsCreateBodyDisplayNameMax = 200

export const visionScannersScoutsCreateBodyNameMax = 64

export const visionScannersScoutsCreateBodyDescriptionMax = 1024

export const visionScannersScoutsCreateBodyConfigOneModelMax = 200

export const visionScannersScoutsCreateBodyConfigOneTagsMax = 10

export const visionScannersScoutsCreateBodyConfigOneMcpGatewayServerIdsMax = 100

export const visionScannersScoutsCreateBodyConfigOneRepositoriesItemMax = 255

export const visionScannersScoutsCreateBodyConfigOneRepositoriesMax = 10

export const visionScannersScoutsCreateBodyConfigOneWriteScopesMax = 9

export const visionScannersScoutsCreateBodyConfigOneRunIntervalMinutesMin = 30
export const visionScannersScoutsCreateBodyConfigOneRunIntervalMinutesMax = 43200

export const visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneChannelMax = 255

export const visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneUsersItemMax = 255

export const visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneUsersItemRegExp = new RegExp(
    '^[UW][A-Z0-9]{4,}\\s\*(\\|.\*)?$'
)
export const visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneUsersMax = 5

export const visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneThreadReportsDefault = true
export const visionScannersScoutsCreateBodyConfigOneRunCronScheduleMax = 100

export const VisionScannersScoutsCreateBody = () => zod
    .object({
        display_name: zod
            .string()
            .max(visionScannersScoutsCreateBodyDisplayNameMax)
            .optional()
            .describe(
                "Name shown wherever people identify this scout, written however you want it — spaces, capitalization, and acronyms are kept as typed, and two scouts may share one. It does not change the scout's skill name, which stays its identity, so renaming a scout keeps its schedule, run history, notes, memory, and links. At most 200 characters; blank means the scout has no name of its own and is labelled from its skill name instead."
            ),
        name: zod
            .string()
            .max(visionScannersScoutsCreateBodyNameMax)
            .optional()
            .describe(
                'Optional skill name for the scout — its permanent identifier, containing only lowercase letters, numbers, and hyphens. Omit it and one is generated from `display_name` (`My APM scout` becomes `my-apm-scout`), with a numeric suffix when that name is taken. Pass it to pick the identifier yourself, or to keep a client written before display names working unchanged. The `signals-scout-` prefix is optional.'
            ),
        description: zod
            .string()
            .max(visionScannersScoutsCreateBodyDescriptionMax)
            .describe('Short description of the signal or behavior this scout investigates.'),
        body: zod
            .string()
            .describe(
                'Complete markdown prompt executed on every scout run. Include any project-specific signal names, thresholds, investigation steps, and report criteria here.'
            ),
        config: zod
            .object({
                model: zod
                    .string()
                    .max(visionScannersScoutsCreateBodyConfigOneModelMax)
                    .nullish()
                    .describe(
                        "Optional model id this scout's runs are pinned to, e.g. `claude-opus-4-5`. Must be one of the platform's agent models; an invalid id is rejected with the available ones listed. Null keeps the default model, chosen by the platform. Early access: the pin can only be set on projects enrolled in the scout model preview, and only takes effect there. Set null to clear it."
                    ),
                tags: zod
                    .array(zod.string())
                    .max(visionScannersScoutsCreateBodyConfigOneTagsMax)
                    .optional()
                    .describe(
                        'Free-form labels for grouping the fleet, e.g. `[\"revenue\", \"on-call\"]`. Normalized to lowercase kebab-case (`On Call` and `on_call` both become `on-call`), deduped, and stored sorted; at most 10 tags, each at most 50 characters once normalized. Pass the full desired set — a write replaces the existing tags rather than merging into them. Filter the config list with the `tags` query parameter.'
                    ),
                structured_output_schema: zod
                    .record(zod.string(), zod.unknown())
                    .nullish()
                    .describe(
                        'Optional JSON Schema (draft 2020-12) describing ONE structured record this scout produces via `scout-record-output` — e.g. a per-report quality judgment (`{\"type\": \"object\", \"properties\": {\"verdict\": {\"enum\": [\"good\", \"bad\", \"unsure\"]}, \"reason\": {\"type\": \"string\"}}, \"required\": [\"verdict\", \"reason\"]}`). The root must be `\"type\": \"object\"`. Setting a schema turns the structured-output channel on: the run prompt renders the schema and every submitted record is validated against it and recorded in the project as a `$scout_structured_output` event, queryable like any event. The channel also requires emit — a dry-run scout has nowhere to record to. Cardinality is the scout\'s call (one record per run, one per judged entity, ...). Null = channel off. Setting a schema requires skill-authoring authorization (the `llm_skill:write` scope and skill editor access) since the scout reads it verbatim in its prompt; clearing it needs only the config write. Records validate against the schema in force when the run was dispatched.'
                    ),
                mcp_gateway_server_ids: zod
                    .array(zod.string())
                    .max(visionScannersScoutsCreateBodyConfigOneMcpGatewayServerIdsMax)
                    .optional()
                    .describe(
                        "MCP gateway servers (by id) this scout's runs may use, chosen from the connections members shared to the whole team. Selection is per scout: an empty list gives the scout no MCP servers. Applies from the scout's next run."
                    ),
                repositories: zod
                    .array(zod.string().max(visionScannersScoutsCreateBodyConfigOneRepositoriesItemMax))
                    .max(visionScannersScoutsCreateBodyConfigOneRepositoriesMax)
                    .optional()
                    .describe(
                        "GitHub repositories this scout clones into its sandbox, each in `organization\/repo` format. Set them for a scout that reads code, so it can search the tree and run the project's own tests instead of reading files one API call at a time. Empty (the default) leaves the sandbox without a checkout. The scout's GitHub access stays read-only either way, so a repository listed here is never writable from a run. At most 10, each reachable through the project's GitHub connection. Applies from the scout's next run."
                    ),
                write_scopes: zod
                    .array(zod.string())
                    .max(visionScannersScoutsCreateBodyConfigOneWriteScopesMax)
                    .optional()
                    .describe(
                        "Extra write access granted to this one scout, as scope strings. The grantable set is `alert:write`, `annotation:write`, `dashboard:write`, `insight:write`, `llm_skill:write`, `replay_scanner:write`, `ticket:write`, `warehouse_table:write`, `warehouse_view:write`. Empty (the default) means the scout reads the project and writes only what every scout may write: notebooks, its findings, and its own memory. Each scope is project-wide and object-level, so a scout holding `dashboard:write` can update or delete any dashboard in the project, not only ones it made. `ticket:write` also lets the scout send customer-facing messages. A reply goes out over the ticket's channel (email, Slack, Teams, or GitHub), and a sent message cannot be taken back. Grant only what this scout maintains. Only the person the scout's runs act as (whoever authored it) or a project admin can set it, and a scoped API key must itself carry each scope it grants. A dry run (`emit=false`) never holds the grant. Applies from the scout's next run."
                    ),
                enabled: zod
                    .boolean()
                    .optional()
                    .describe('Whether this scout runs on its schedule. Defaults to true.'),
                emit: zod
                    .boolean()
                    .optional()
                    .describe(
                        'Whether the scout writes findings to the inbox. False = dry-run: it runs and logs but emits nothing. Defaults to true.'
                    ),
                run_interval_minutes: zod
                    .number()
                    .min(visionScannersScoutsCreateBodyConfigOneRunIntervalMinutesMin)
                    .max(visionScannersScoutsCreateBodyConfigOneRunIntervalMinutesMax)
                    .optional()
                    .describe('Minutes between runs (30–43200). Defaults to 1440 (every 24 hours).'),
                output_destinations: zod
                    .object({
                        slack: zod
                            .union([
                                zod.object({
                                    integration_id: zod
                                        .number()
                                        .min(1)
                                        .describe(
                                            "ID of the Slack integration whose bot posts this scout's findings and reports."
                                        ),
                                    channel: zod
                                        .string()
                                        .max(
                                            visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneChannelMax
                                        )
                                        .nullish()
                                        .describe(
                                            "Slack channel target in the channel picker's `channel_id|#channel-name` format. Null while choosing a channel; no messages are sent until a channel or user is set."
                                        ),
                                    users: zod
                                        .array(
                                            zod
                                                .string()
                                                .max(
                                                    visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneUsersItemMax
                                                )
                                                .regex(
                                                    visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneUsersItemRegExp
                                                )
                                        )
                                        .min(1)
                                        .max(
                                            visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneUsersMax
                                        )
                                        .nullish()
                                        .describe(
                                            'Slack members to send output to as direct messages, each in `member_id|@display-name` format (a bare member ID like `U0123ABC456` also works). Each member gets their own DM from the PostHog app; at most 5. Set either this or `channel`, not both. Useful for personal scouts where a DM beats a channel.'
                                        ),
                                    thread_reports: zod
                                        .boolean()
                                        .default(
                                            visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneThreadReportsDefault
                                        )
                                        .describe(
                                            "When true, post a report as a thread: a short lead in the channel and the rest split into replies at the summary's section labels, which can be Markdown headings or bold labels. Keeps a long summary from being clipped at Slack's section limit. On by default; set it false to post a single message, which can truncate a long summary. It does not change how findings post."
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                'Slack destination for each emitted scout finding or report. Null or omitted disables Slack delivery.'
                            ),
                        webhook: zod
                            .union([
                                zod.object({
                                    hog_function_id: zod
                                        .string()
                                        .describe(
                                            "Id of the CDP destination delivering this scout's reports. Set by the product that provisioned it, so it can find that destination again to update or remove it."
                                        ),
                                }),
                                zod.null(),
                            ])
                            .optional()
                            .describe(
                                "The CDP destination another product provisioned for this scout's reports. Null or omitted means no webhook. Unlike Slack, Signals does not deliver this itself: the reference lives here so the owning product can manage the destination's lifecycle."
                            ),
                    })
                    .optional()
                    .describe('Destinations that receive each finding or report this scout emits. Empty by default.'),
                network_access: zod
                    .enum(['trusted', 'full'])
                    .describe('\* `trusted` - Trusted domains only\n\* `full` - Full')
                    .optional()
                    .describe(
                        "What the scout's sandbox can reach over the network while it runs. Defaults to `trusted`, the platform's trusted-domain allowlist (PostHog, GitHub, common package registries). Set `full` to let this scout reach any site, for skills that read external sources such as documentation or papers.\n\n\* `trusted` - Trusted domains only\n\* `full` - Full"
                    ),
                auto_pause_exempt: zod
                    .boolean()
                    .optional()
                    .describe(
                        'Exempt this scout from the inactivity pause, which otherwise switches off a scout that goes a fortnight without surfacing anything anyone engages with. Set it on watchdog scouts whose value is staying quiet. Defaults to false.'
                    ),
                run_cron_schedule: zod
                    .string()
                    .max(visionScannersScoutsCreateBodyConfigOneRunCronScheduleMax)
                    .nullish()
                    .describe(
                        "Optional five-field cron expression, e.g. '30 9 \* \* \*' (daily at 09:30), '0 9,17 \* \* \*' (twice daily), or '0 9 \* \* 1-5' (weekday mornings). Evaluated in the project timezone. Takes precedence over `run_interval_minutes`; occurrences must be at least 30 minutes apart."
                    ),
            })
            .describe('Schedule, enablement, and delivery options accepted while creating a scout.')
            .optional()
            .describe(
                'Optional schedule, enablement, dry-run posture, and delivery settings. Defaults to an enabled, emitting scout on the daily interval with no external destination.'
            ),
    })
    .describe(
        "A scout to stand up for this scanner. The scanner comes from the URL, never the body: it is\nwhat the caller's access is checked against, and what the scout is recorded as belonging to.\n\nInherits the Signals scout definition so a scout created here clears the same name and prompt-size\nbars as one created through the generic endpoint."
    )

/**
 * Draft a full scanner configuration from a natural-language goal, for the goal-based creation flow.
 */
export const VisionScannersDraftCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersDraftCreateBodyGoalMax = 2000

export const visionScannersDraftCreateBodyMonthlyCreditBudgetMax = 100000000

export const VisionScannersDraftCreateBody = () => zod
    .object({
        goal: zod
            .string()
            .max(visionScannersDraftCreateBodyGoalMax)
            .describe("What the user wants to accomplish, e.g. 'find out where users get stuck during onboarding'."),
        monthly_credit_budget: zod
            .number()
            .min(1)
            .max(visionScannersDraftCreateBodyMonthlyCreditBudgetMax)
            .optional()
            .describe(
                "Goal-based flow only: credits a month to spend (1 credit = $0.01). The draft picks the `model`, then solves `sampling_mode` and `sampling_rate` so the projected spend lands on this number, and sets `credit_limit` to it as a hard cap. Omitted on the legacy flow, and ignored while the goal-based flow's flag is off for the caller."
            ),
    })
    .describe("Body of POST \/vision\/scanners\/draft\/ — the user's goal, stated in their own words.")

/**
 * Estimate the observation volume a proposed scanner would generate, for the pre-save cost preview.
 */
export const VisionScannersEstimateCreateParams = () => zod.object({
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

export const VisionScannersEstimateCreateBody = () => zod
    .object({
        query: zod
            .unknown()
            .optional()
            .describe(
                'Proposed `RecordingsQuery` for the candidate filter. `date_from`\/`date_to` are ignored — the estimate scans a recent window (`window_days` in the response) and scales it to 30 days. Omit to estimate against all recordings.'
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
            .enum(['gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-3.8-flash'])
            .describe(
                '\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.8-flash` - Gemini 3.8 Flash'
            )
            .default(visionScannersEstimateCreateBodyModelDefault)
            .describe(
                'Proposed model; determines `credits_per_observation` in the response.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.8-flash` - Gemini 3.8 Flash'
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
 *
 * With `scanner_type` set to `summarizer`, this is how you get PostHog's own AI summary for a
 * recording ID. It resolves to the Summarize button's own scanner only when the prompt and
 * `scanner_config` match what the button sends, since the config is what the key fingerprints.
 */
export const VisionScannersInlineScanCreateParams = () => zod.object({
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

export const VisionScannersInlineScanCreateBody = () => zod
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
                "What the scan produces. Defaults to monitor, an open-ended observation against the prompt. Use `summarizer` to get PostHog's own AI summary of a recording. An inline scan is keyed by its whole config, so the Summarize button in the replay player shares this scan only when the prompt and `scanner_config` match the ones it sends.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer"
            ),
        scanner_config: zod
            .unknown()
            .optional()
            .describe(
                'Type-specific configuration beyond the prompt: `tags` for a classifier, `scale` for a scorer, optional `length` for a summarizer. Omit it for a monitor. `prompt` belongs in the `prompt` field and is rejected here.'
            ),
        model: zod
            .enum(['gemini-3.5-flash-lite', 'gemini-3-flash-preview', 'gemini-3.8-flash'])
            .describe(
                '\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.8-flash` - Gemini 3.8 Flash'
            )
            .default(visionScannersInlineScanCreateBodyModelDefault)
            .describe(
                'Model to scan with. Determines what each observation costs in credits.\n\n\* `gemini-3.5-flash-lite` - Gemini 3.5 Flash Lite\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.8-flash` - Gemini 3.8 Flash'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/inline_scan\/ - a prompt plus the sessions to point it at.')

/**
 * Team-wide scanner counts — independent of list filters, so the overview stays stable.
 */
export const VisionScannersStatsRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

/**
 * Suggest classifier tags grounded in the scanner's own observations and the org's product data.
 */
export const VisionScannersSuggestTagsCreateParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersSuggestTagsCreateBodyPromptMax = 10000

export const visionScannersSuggestTagsCreateBodyTagsItemMax = 200

export const visionScannersSuggestTagsCreateBodyTagsMax = 200

export const visionScannersSuggestTagsCreateBodyMultiLabelDefault = true
export const visionScannersSuggestTagsCreateBodyAllowFreeformTagsDefault = false

export const VisionScannersSuggestTagsCreateBody = () => zod
    .object({
        prompt: zod
            .string()
            .max(visionScannersSuggestTagsCreateBodyPromptMax)
            .describe("The classifier's instruction prompt — the single dimension to categorize sessions by."),
        tags: zod
            .array(zod.string().max(visionScannersSuggestTagsCreateBodyTagsItemMax))
            .max(visionScannersSuggestTagsCreateBodyTagsMax)
            .optional()
            .describe('The categories already configured, so suggestions never duplicate one the user has.'),
        multi_label: zod
            .boolean()
            .default(visionScannersSuggestTagsCreateBodyMultiLabelDefault)
            .describe('Whether the classifier assigns multiple tags per session.'),
        allow_freeform_tags: zod
            .boolean()
            .default(visionScannersSuggestTagsCreateBodyAllowFreeformTagsDefault)
            .describe('Whether the classifier may emit tags outside the fixed vocabulary.'),
        scanner_id: zod
            .string()
            .nullish()
            .describe(
                'Existing scanner to ground suggestions in its own observations (the tags and reasoning it has already produced on real recordings). Omit for an unsaved scanner.'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/suggest_tags\/ — the classifier config currently being edited.')

/**
 * Succeeded observations in the window worth watching, ranked — feeds the What to watch tab.
 */
export const VisionScannersWatchFeedRetrieveParams = () => zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to \/api\/projects\/."
        ),
})

export const visionScannersWatchFeedRetrieveQueryDateFromDefault = `-7d`

export const visionScannersWatchFeedRetrieveQueryLimitDefault = 20
export const visionScannersWatchFeedRetrieveQueryLimitMax = 50

export const VisionScannersWatchFeedRetrieveQueryParams = () => zod.object({
    date_from: zod
        .string()
        .min(1)
        .default(visionScannersWatchFeedRetrieveQueryDateFromDefault)
        .describe(
            "Only observations created at or after this time. Accepts ISO 8601, a relative date like `-7d`, or `now`; values without an explicit offset are interpreted in the project's timezone. The window between `date_from` and `date_to` may span at most 90 days."
        ),
    date_to: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'Only observations created at or before this time. Same formats as `date_from`; omit it to query through the current time.'
        ),
    limit: zod
        .number()
        .min(1)
        .max(visionScannersWatchFeedRetrieveQueryLimitMax)
        .default(visionScannersWatchFeedRetrieveQueryLimitDefault)
        .describe(
            'Ceiling on feed items to return, at most 50. The feed is bounded, not paginated, and routinely returns far fewer: a window is not padded to this number with clips that carry no finding.'
        ),
    scanner_ids: zod
        .string()
        .min(1)
        .optional()
        .describe('Comma-separated scanner UUIDs to restrict the feed to. Defaults to every scanner you can read.'),
    scanner_type: zod
        .enum(['monitor', 'classifier', 'scorer', 'summarizer'])
        .optional()
        .describe(
            'Restrict the feed to observations from scanners of this type.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer'
        ),
    search: zod
        .string()
        .min(1)
        .optional()
        .describe(
            "Case-insensitive text to match against the scan's own words (title, summary, reasoning, and the notability sentence) and the scanner's name. Applied before ranking, so it searches the whole window rather than the items that would have surfaced without it."
        ),
    tags: zod
        .string()
        .min(1)
        .optional()
        .describe(
            'Comma-separated scanner tags to restrict the feed to. A team with many scanners uses these to follow one area without naming every scanner in it.'
        ),
})
