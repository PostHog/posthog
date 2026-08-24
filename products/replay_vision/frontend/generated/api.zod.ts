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
export const visionActionsCreateBodyAlertConfigOneIncludeReasoningDefault = false

export const VisionActionsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(visionActionsCreateBodyNameMax)
            .describe('Human-readable action name. Unique within the team.'),
        scanner: zod
            .uuid()
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
 * Set or update the observation's shared label: whether the scanner scored the session correctly, plus optional feedback on what it got wrong. One label per observation, shared across the team; these labels feed prompt improvement. Requires editor access to the scanner.
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
 * Apply this scanner to many sessions on demand. Starts as many as fit under the in-flight
 * caps and monthly credit quota, reporting the rest as skipped rather than failing the batch.
 */
export const visionScannersBulkObserveCreateBodySessionIdsItemMax = 128

export const visionScannersBulkObserveCreateBodySessionIdsMax = 200

export const VisionScannersBulkObserveCreateBody = /* @__PURE__ */ zod
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
 * Create a backfill: freeze the scanner config, enumerate the exact candidate set, start the tick schedule.
 *
 * The enumeration reruns here rather than trusting the client-confirmed estimate: the count is
 * billing-relevant, so the authoritative value is computed server-side at creation time. New
 * settled sessions between estimate and confirm can nudge total_count slightly.
 */
export const VisionScannersBackfillsCreateBody = /* @__PURE__ */ zod.object({
    window_start: zod.iso
        .datetime({ offset: true })
        .describe('Inclusive lower bound of the historical window to scan.'),
    window_end: zod.iso
        .datetime({ offset: true })
        .describe('Exclusive upper bound of the window; clamped server-side to now.'),
})

/**
 * Stop an active backfill; already-dispatched observations finish, nothing new dispatches.
 */
export const VisionScannersBackfillsCancelCreateBody = /* @__PURE__ */ zod.looseObject({})

/**
 * Restart a backfill that paused when the monthly quota ran out.
 */
export const VisionScannersBackfillsResumeCreateBody = /* @__PURE__ */ zod.looseObject({})

/**
 * Exactly enumerate what a backfill over the given window would dispatch and cost.
 */
export const VisionScannersBackfillsEstimateCreateBody = /* @__PURE__ */ zod.object({
    window_start: zod.iso
        .datetime({ offset: true })
        .describe('Inclusive lower bound of the historical window to scan.'),
    window_end: zod.iso
        .datetime({ offset: true })
        .describe('Exclusive upper bound of the window; clamped server-side to now.'),
})

/**
 * Set or update the observation's shared label: whether the scanner scored the session correctly, plus optional feedback on what it got wrong. One label per observation, shared across the team; these labels feed prompt improvement. Requires editor access to the scanner.
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
 * Apply this suggestion: write a config to the scanner (the prompt plus any type-specific config such as classifier tags or the monitor allow_inconclusive flag), bumping the scanner version, and mark the suggestion applied. Pass `config` to apply an edited subset of the recommendation; omit it to apply the full suggested config. Only the current pending suggestion can be applied. Requires session recording edit access.
 */
export const VisionScannersPromptSuggestionsApplyCreateBody = /* @__PURE__ */ zod.object({
    config: zod
        .unknown()
        .optional()
        .describe(
            "The edited config to apply, assembled from the recommendation's approved fields. Omit to apply the full suggested config unchanged."
        ),
})

/**
 * Test this suggestion before applying it: re-run the scanner with the suggested prompt against already-rated sessions in the background and compare each fresh output with the stored one. Results land on the suggestion's `evaluation` field. Poll `current` while status is running. `session_limit` controls how many rated sessions are re-run (thumbs-down prioritized, up to `evaluation_session_cap`). Each successful re-run charges credits like a normal observation of the same model. The request is refused with 402 when the planned credits exceed what is left for the current billing period, either the org's limit or this scanner's own. Monitor and classifier scanners get a kept/fixed/regressed classification, while scorer and summarizer scanners show the raw before and after output. Requires session recording edit access.
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
    config: zod
        .unknown()
        .optional()
        .describe(
            "The edited config to test, assembled from the recommendation's approved fields. Omit to test the full suggested config."
        ),
})

/**
 * Create a scout that watches this scanner, recorded as belonging to it.
 */
export const visionScannersScoutsCreateBodyNameMax = 64

export const visionScannersScoutsCreateBodyDescriptionMax = 4096

export const visionScannersScoutsCreateBodyConfigOneRunIntervalMinutesMin = 30
export const visionScannersScoutsCreateBodyConfigOneRunIntervalMinutesMax = 43200

export const visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneChannelMax = 255

export const visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneThreadReportsDefault = false
export const visionScannersScoutsCreateBodyConfigOneRunCronScheduleMax = 100

export const visionScannersScoutsCreateBodyConfigOneModelMax = 200

export const visionScannersScoutsCreateBodyConfigOneTagsMax = 10

export const visionScannersScoutsCreateBodyConfigOneMcpGatewayServerIdsMax = 100

export const VisionScannersScoutsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(visionScannersScoutsCreateBodyNameMax)
            .describe(
                'Unique scout name. Must start with `signals-scout-` and contain only lowercase letters, numbers, and hyphens.'
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
                                            "Slack channel target in the channel picker's `channel_id|#channel-name` format. Null while choosing a channel; no messages are sent until it is set."
                                        ),
                                    thread_reports: zod
                                        .boolean()
                                        .default(
                                            visionScannersScoutsCreateBodyConfigOneOutputDestinationsOneSlackOneThreadReportsDefault
                                        )
                                        .describe(
                                            "When true, post a report as a thread: a short lead in the channel and the rest split by the report's Markdown headings into replies. Keeps a long summary from being clipped at Slack's section limit. Off by default, and it does not change how findings post."
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
                    .array(zod.uuid())
                    .max(visionScannersScoutsCreateBodyConfigOneMcpGatewayServerIdsMax)
                    .optional()
                    .describe(
                        "MCP gateway servers (by id) this scout's runs may use, chosen from the connections members shared to the whole team. Selection is per scout: an empty list gives the scout no MCP servers. Applies from the scout's next run."
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
export const visionScannersDraftCreateBodyGoalMax = 2000

export const VisionScannersDraftCreateBody = /* @__PURE__ */ zod
    .object({
        goal: zod
            .string()
            .max(visionScannersDraftCreateBodyGoalMax)
            .describe("What the user wants to accomplish, e.g. 'find out where users get stuck during onboarding'."),
    })
    .describe("Body of POST \/vision\/scanners\/draft\/ — the user's goal, stated in their own words.")

/**
 * Estimate the observation volume a proposed scanner would generate, for the pre-save cost preview.
 */
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
            .uuid()
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
            .uuid()
            .nullish()
            .describe(
                'Existing scanner to ground suggestions in its own observations (the tags and reasoning it has already produced on real recordings). Omit for an unsaved scanner.'
            ),
    })
    .describe('Body of POST \/vision\/scanners\/suggest_tags\/ — the classifier config currently being edited.')
