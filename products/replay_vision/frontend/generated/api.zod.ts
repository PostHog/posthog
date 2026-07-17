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
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const visionActionsCreateBodyNameMax = 255

export const visionActionsCreateBodyTriggerConfigOneTimezoneDefault = `UTC`
export const visionActionsCreateBodySynthesisConfigOnePromptGuideMax = 500

export const visionActionsCreateBodyAlertConfigOneFrequencyDefault = `on_breach`
export const visionActionsCreateBodyAlertConfigOneMetricDefault = `count`
export const visionActionsCreateBodyAlertConfigOneDirectionDefault = `above`

export const VisionActionsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(visionActionsCreateBodyNameMax)
        .describe('Human-readable action name. Unique within the team.'),
    scanner: zod.uuid().describe('Scanner whose observations this action operates on. Must belong to the same team.'),
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
                        .enum(['slack'])
                        .describe('\* `slack` - Slack')
                        .describe("Destination channel type. MVP supports 'slack' only.\n\n\* `slack` - Slack"),
                    integration_id: zod
                        .number()
                        .describe('ID of the Slack Integration on this team used to deliver the summary.'),
                    channel: zod.string().describe('Slack channel ID or name the summary is posted to.'),
                })
                .describe('A single delivery destination. MVP supports Slack only.')
        )
        .optional()
        .describe('List of delivery destinations the synthesized summary is sent to.'),
})

/**
 * CRUD for Replay Vision actions — scheduled "and then…" automations over a scanner's observations.
 */
export const visionActionsPartialUpdateBodyNameMax = 255

export const visionActionsPartialUpdateBodyTriggerConfigOneTimezoneDefault = `UTC`
export const visionActionsPartialUpdateBodySynthesisConfigOnePromptGuideMax = 500

export const visionActionsPartialUpdateBodyAlertConfigOneFrequencyDefault = `on_breach`
export const visionActionsPartialUpdateBodyAlertConfigOneMetricDefault = `count`
export const visionActionsPartialUpdateBodyAlertConfigOneDirectionDefault = `above`

export const VisionActionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(visionActionsPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable action name. Unique within the team.'),
    scanner: zod
        .uuid()
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
                        .enum(['slack'])
                        .describe('\* `slack` - Slack')
                        .describe("Destination channel type. MVP supports 'slack' only.\n\n\* `slack` - Slack"),
                    integration_id: zod
                        .number()
                        .describe('ID of the Slack Integration on this team used to deliver the summary.'),
                    channel: zod.string().describe('Slack channel ID or name the summary is posted to.'),
                })
                .describe('A single delivery destination. MVP supports Slack only.')
        )
        .optional()
        .describe('List of delivery destinations the synthesized summary is sent to.'),
})

/**
 * Set or update the observation's shared label: whether the scanner scored the session correctly, plus optional feedback on what it got wrong. One label per observation, shared across the team; these labels feed prompt improvement. Requires session recording edit access.
 */
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
 * CRUD for Replay Vision scanners.
 */
export const visionScannersCreateBodyNameMax = 255

export const visionScannersCreateBodyDescriptionMax = 1000

export const visionScannersCreateBodySamplingRateMin = 0
export const visionScannersCreateBodySamplingRateMax = 1

export const VisionScannersCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(visionScannersCreateBodyNameMax)
        .describe('Human-readable scanner name. Unique within the team.'),
    description: zod
        .string()
        .max(visionScannersCreateBodyDescriptionMax)
        .optional()
        .describe('Free-form description shown in the scanner management UI.'),
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
    provider: zod
        .enum(['google'])
        .describe('\* `google` - Google')
        .optional()
        .describe('LLM provider. v1 is Google-only.\n\n\* `google` - Google'),
    model: zod
        .enum(['gemini-2.5-flash', 'gemini-3-flash-preview', 'gemini-3.5-flash'])
        .describe(
            '\* `gemini-2.5-flash` - Gemini 2.5 Flash\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.5-flash` - Gemini 3.5 Flash'
        )
        .describe(
            'Concrete model to use for this scanner.\n\n\* `gemini-2.5-flash` - Gemini 2.5 Flash\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.5-flash` - Gemini 3.5 Flash'
        ),
    enabled: zod
        .boolean()
        .optional()
        .describe("When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work."),
    emits_signals: zod
        .boolean()
        .optional()
        .describe(
            'When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals.'
        ),
})

/**
 * CRUD for Replay Vision scanners.
 */
export const visionScannersPartialUpdateBodyNameMax = 255

export const visionScannersPartialUpdateBodyDescriptionMax = 1000

export const visionScannersPartialUpdateBodySamplingRateMin = 0
export const visionScannersPartialUpdateBodySamplingRateMax = 1

export const VisionScannersPartialUpdateBody = /* @__PURE__ */ zod.object({
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
    provider: zod
        .enum(['google'])
        .describe('\* `google` - Google')
        .optional()
        .describe('LLM provider. v1 is Google-only.\n\n\* `google` - Google'),
    model: zod
        .enum(['gemini-2.5-flash', 'gemini-3-flash-preview', 'gemini-3.5-flash'])
        .describe(
            '\* `gemini-2.5-flash` - Gemini 2.5 Flash\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.5-flash` - Gemini 3.5 Flash'
        )
        .optional()
        .describe(
            'Concrete model to use for this scanner.\n\n\* `gemini-2.5-flash` - Gemini 2.5 Flash\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.5-flash` - Gemini 3.5 Flash'
        ),
    enabled: zod
        .boolean()
        .optional()
        .describe("When false, the reconciler removes the scanner's Temporal schedule. On-demand triggers still work."),
    emits_signals: zod
        .boolean()
        .optional()
        .describe(
            'When true, the prompt is augmented with the Signal side mission and the scanner emits PostHog Signals.'
        ),
})

/**
 * Save the users this scanner matched as a static cohort, for surveys, funnels, and retention analysis.
 */
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
 * Apply this scanner to one specific session, on demand. Returns 202 with the workflow handle.
 */
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
 * Set or update the observation's shared label: whether the scanner scored the session correctly, plus optional feedback on what it got wrong. One label per observation, shared across the team; these labels feed prompt improvement. Requires session recording edit access.
 */
export const visionScannersObservationsLabelCreateBodyFeedbackDefault = ``
export const visionScannersObservationsLabelCreateBodyFeedbackMax = 5000

export const VisionScannersObservationsLabelCreateBody = /* @__PURE__ */ zod
    .object({
        is_correct: zod.boolean().describe('True if the scanner scored this session correctly, false if not.'),
        feedback: zod
            .string()
            .max(visionScannersObservationsLabelCreateBodyFeedbackMax)
            .default(visionScannersObservationsLabelCreateBodyFeedbackDefault)
            .describe(
                'Optional written context on the rating, for thumbs-up and thumbs-down alike: what the scanner got right or wrong, or what it should have concluded.'
            ),
    })
    .describe("The team's shared judgement on whether the scanner scored this session correctly.")

/**
 * Test this suggestion before applying it: re-run the scanner with the suggested prompt against already-rated sessions in the background and compare each fresh output with the stored one. Results land on the suggestion's `evaluation` field. Poll `current` while status is running. `session_limit` controls how many rated sessions are re-run (thumbs-down prioritized, up to `evaluation_session_cap`). Each successful re-run charges credits like a normal observation of the same model. The request is refused with 402 when the planned credits exceed what is left of the monthly limit. Monitor and classifier scanners get a kept/fixed/regressed classification, while scorer and summarizer scanners show the raw before and after output. Requires session recording edit access.
 */
export const visionScannersPromptSuggestionsEvaluateCreateBodySessionLimitDefault = 10
export const visionScannersPromptSuggestionsEvaluateCreateBodySessionLimitMax = 100

export const VisionScannersPromptSuggestionsEvaluateCreateBody = /* @__PURE__ */ zod.object({
    session_limit: zod
        .number()
        .min(1)
        .max(visionScannersPromptSuggestionsEvaluateCreateBodySessionLimitMax)
        .default(visionScannersPromptSuggestionsEvaluateCreateBodySessionLimitDefault)
        .describe(
            'How many rated sessions to re-run, thumbs-down prioritized. Each successful re-run charges credits like a normal observation of the same model. Defaults to 10. The maximum is `evaluation_session_cap`.'
        ),
})

/**
 * Estimate the observation volume a proposed scanner would generate, for the pre-save cost preview.
 */
export const visionScannersEstimateCreateBodySamplingRateDefault = 1
export const visionScannersEstimateCreateBodySamplingRateMin = 0
export const visionScannersEstimateCreateBodySamplingRateMax = 1

export const visionScannersEstimateCreateBodySamplingModeDefault = `comprehensive`
export const visionScannersEstimateCreateBodyModelDefault = `gemini-3-flash-preview`

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
            .uuid()
            .nullish()
            .describe(
                "The scanner being edited, excluded from `other_enabled_scanners_monthly_credits` so its stored estimate isn't double-counted in the forecast. Omit (or null) when estimating a brand-new scanner."
            ),
        model: zod
            .enum(['gemini-2.5-flash', 'gemini-3-flash-preview', 'gemini-3.5-flash'])
            .describe(
                '\* `gemini-2.5-flash` - Gemini 2.5 Flash\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.5-flash` - Gemini 3.5 Flash'
            )
            .default(visionScannersEstimateCreateBodyModelDefault)
            .describe(
                'Proposed model; determines `credits_per_observation` in the response.\n\n\* `gemini-2.5-flash` - Gemini 2.5 Flash\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.5-flash` - Gemini 3.5 Flash'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/estimate\/ — a proposed, unsaved scanner config.')

/**
 * Suggest classifier tags grounded in the scanner's own observations and the org's product data.
 */
export const visionScannersSuggestTagsCreateBodyPromptMax = 10000

export const visionScannersSuggestTagsCreateBodyTagsItemMax = 200

export const visionScannersSuggestTagsCreateBodyTagsMax = 200

export const visionScannersSuggestTagsCreateBodyMultiLabelDefault = true
export const visionScannersSuggestTagsCreateBodyAllowFreeformTagsDefault = false

export const VisionScannersSuggestTagsCreateBody = /* @__PURE__ */ zod
    .object({
        prompt: zod
            .string()
            .max(visionScannersSuggestTagsCreateBodyPromptMax)
            .describe("The classifier's instruction prompt — the single dimension to categorize sessions by."),
        tags: zod
            .array(zod.string().max(visionScannersSuggestTagsCreateBodyTagsItemMax))
            .max(visionScannersSuggestTagsCreateBodyTagsMax)
            .optional()
            .describe('The current tag vocabulary, so suggestions never duplicate a tag the user already has.'),
        multi_label: zod
            .boolean()
            .default(visionScannersSuggestTagsCreateBodyMultiLabelDefault)
            .describe('Whether the classifier assigns multiple tags per session.'),
        allow_freeform_tags: zod
            .boolean()
            .default(visionScannersSuggestTagsCreateBodyAllowFreeformTagsDefault)
            .describe('Whether the classifier may emit tags outside the fixed vocabulary.'),
        scanner_id: zod
            .uuid()
            .nullish()
            .describe(
                'Existing scanner to ground suggestions in its own observations (the tags and reasoning it has already produced on real recordings). Omit for an unsaved scanner.'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/suggest_tags\/ — the classifier config currently being edited.')
