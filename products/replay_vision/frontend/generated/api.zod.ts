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

export const VisionActionsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(visionActionsCreateBodyNameMax)
        .describe('Human-readable action name. Unique within the team.'),
    scanner: zod.uuid().describe('Scanner whose observations this action operates on. Must belong to the same team.'),
    enabled: zod.boolean().optional().describe('When false, the scheduler skips this action.'),
    trigger_type: zod
        .enum(['schedule', 'threshold'])
        .describe('\* `schedule` - Schedule\n\* `threshold` - Threshold')
        .optional()
        .describe(
            "What fires the action. MVP supports 'schedule' only.\n\n\* `schedule` - Schedule\n\* `threshold` - Threshold"
        ),
    mode: zod
        .enum(['group_summary', 'per_observation'])
        .describe('\* `group_summary` - Group summary\n\* `per_observation` - Per observation')
        .optional()
        .describe(
            "What the action produces. MVP supports 'group_summary' only.\n\n\* `group_summary` - Group summary\n\* `per_observation` - Per observation"
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
            scanner_type: zod
                .string()
                .optional()
                .describe('Filter observations by scanner type (monitor\/classifier\/scorer\/summarizer).'),
            scanner_ids: zod
                .array(zod.string())
                .optional()
                .describe('Restrict to observations produced by these scanner IDs.'),
            verdict: zod.string().optional().describe('Filter to observations with this monitor verdict.'),
            tags: zod
                .array(zod.string())
                .optional()
                .describe('Filter to observations carrying any of these classifier tags.'),
            min_score: zod.number().optional().describe('Lower bound (inclusive) on scorer score.'),
            max_score: zod.number().optional().describe('Upper bound (inclusive) on scorer score.'),
            status: zod.string().optional().describe('Filter to observations with this processing status.'),
            window_days: zod
                .number()
                .optional()
                .describe('Lookback window in days for the observations gathered at synthesis time.'),
        })
        .describe(
            'Observation filter applied at synthesis time. All keys optional; this typed shape is the\nallowlist, so unknown input keys are dropped rather than persisted.'
        )
        .optional()
        .describe('Observation filter applied at synthesis time.'),
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
    trigger_type: zod
        .enum(['schedule', 'threshold'])
        .describe('\* `schedule` - Schedule\n\* `threshold` - Threshold')
        .optional()
        .describe(
            "What fires the action. MVP supports 'schedule' only.\n\n\* `schedule` - Schedule\n\* `threshold` - Threshold"
        ),
    mode: zod
        .enum(['group_summary', 'per_observation'])
        .describe('\* `group_summary` - Group summary\n\* `per_observation` - Per observation')
        .optional()
        .describe(
            "What the action produces. MVP supports 'group_summary' only.\n\n\* `group_summary` - Group summary\n\* `per_observation` - Per observation"
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
            scanner_type: zod
                .string()
                .optional()
                .describe('Filter observations by scanner type (monitor\/classifier\/scorer\/summarizer).'),
            scanner_ids: zod
                .array(zod.string())
                .optional()
                .describe('Restrict to observations produced by these scanner IDs.'),
            verdict: zod.string().optional().describe('Filter to observations with this monitor verdict.'),
            tags: zod
                .array(zod.string())
                .optional()
                .describe('Filter to observations carrying any of these classifier tags.'),
            min_score: zod.number().optional().describe('Lower bound (inclusive) on scorer score.'),
            max_score: zod.number().optional().describe('Upper bound (inclusive) on scorer score.'),
            status: zod.string().optional().describe('Filter to observations with this processing status.'),
            window_days: zod
                .number()
                .optional()
                .describe('Lookback window in days for the observations gathered at synthesis time.'),
        })
        .describe(
            'Observation filter applied at synthesis time. All keys optional; this typed shape is the\nallowlist, so unknown input keys are dropped rather than persisted.'
        )
        .optional()
        .describe('Observation filter applied at synthesis time.'),
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
 * CRUD for Replay Vision scanners.
 */
export const visionScannersCreateBodyNameMax = 255

export const visionScannersCreateBodyDescriptionMax = 1000

export const visionScannersCreateBodySamplingRateMin = 0
export const visionScannersCreateBodySamplingRateMax = 1

export const visionScannersCreateBodyMomentsConfigOneEventsItemEventMax = 400

export const visionScannersCreateBodyMomentsConfigOneBeforeSecondsMin = 5
export const visionScannersCreateBodyMomentsConfigOneBeforeSecondsMax = 300

export const visionScannersCreateBodyMomentsConfigOneAfterSecondsMin = 5
export const visionScannersCreateBodyMomentsConfigOneAfterSecondsMax = 300

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
    scan_scope: zod
        .enum(['recording', 'moments'])
        .describe('\* `recording` - Entire recording\n\* `moments` - Moments around events')
        .optional()
        .describe(
            'How much of each matched recording the scanner watches: `recording` scans the whole recording; `moments` scans short clips around each occurrence of the focus events. Fixed after creation.\n\n\* `recording` - Entire recording\n\* `moments` - Moments around events'
        ),
    moments_config: zod
        .union([
            zod
                .object({
                    events: zod
                        .array(
                            zod
                                .object({
                                    event: zod
                                        .string()
                                        .max(visionScannersCreateBodyMomentsConfigOneEventsItemEventMax)
                                        .describe('Event name whose occurrences anchor moments.'),
                                    properties: zod
                                        .array(zod.record(zod.string(), zod.unknown()))
                                        .optional()
                                        .describe(
                                            'Property filters the occurrence must also match; standard PostHog property filter shapes.'
                                        ),
                                })
                                .describe(
                                    'Mirrors `moments.MomentEvent` for OpenAPI generation; writes validate via the pydantic model.'
                                )
                        )
                        .describe('Focus events (1-10); a moment is scanned around each occurrence of any of them.'),
                    before_seconds: zod
                        .number()
                        .min(visionScannersCreateBodyMomentsConfigOneBeforeSecondsMin)
                        .max(visionScannersCreateBodyMomentsConfigOneBeforeSecondsMax)
                        .optional()
                        .describe('Clip seconds included before the focus event. Defaults to 60.'),
                    after_seconds: zod
                        .number()
                        .min(visionScannersCreateBodyMomentsConfigOneAfterSecondsMin)
                        .max(visionScannersCreateBodyMomentsConfigOneAfterSecondsMax)
                        .optional()
                        .describe('Clip seconds included after the focus event. Defaults to 60.'),
                })
                .describe(
                    'Mirrors `moments.MomentsConfig` for OpenAPI generation; writes validate via the pydantic model.'
                ),
            zod.null(),
            zod.null(),
        ])
        .optional()
        .describe(
            'For moments-scoped scanners: the focus events (name + optional property filters) and clip bounds (`before_seconds`\/`after_seconds`, 5-300 each, defaulting to 60). Must be null for recording-scoped scanners.'
        ),
    provider: zod
        .enum(['google'])
        .describe('\* `google` - Google')
        .optional()
        .describe('LLM provider. v1 is Google-only.\n\n\* `google` - Google'),
    model: zod
        .enum(['gemini-3-flash-preview', 'gemini-3.1-flash-lite-preview'])
        .describe(
            '\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite'
        )
        .describe(
            'Concrete model to use for this scanner.\n\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite'
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

export const visionScannersPartialUpdateBodyMomentsConfigOneEventsItemEventMax = 400

export const visionScannersPartialUpdateBodyMomentsConfigOneBeforeSecondsMin = 5
export const visionScannersPartialUpdateBodyMomentsConfigOneBeforeSecondsMax = 300

export const visionScannersPartialUpdateBodyMomentsConfigOneAfterSecondsMin = 5
export const visionScannersPartialUpdateBodyMomentsConfigOneAfterSecondsMax = 300

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
    scan_scope: zod
        .enum(['recording', 'moments'])
        .describe('\* `recording` - Entire recording\n\* `moments` - Moments around events')
        .optional()
        .describe(
            'How much of each matched recording the scanner watches: `recording` scans the whole recording; `moments` scans short clips around each occurrence of the focus events. Fixed after creation.\n\n\* `recording` - Entire recording\n\* `moments` - Moments around events'
        ),
    moments_config: zod
        .union([
            zod
                .object({
                    events: zod
                        .array(
                            zod
                                .object({
                                    event: zod
                                        .string()
                                        .max(visionScannersPartialUpdateBodyMomentsConfigOneEventsItemEventMax)
                                        .describe('Event name whose occurrences anchor moments.'),
                                    properties: zod
                                        .array(zod.record(zod.string(), zod.unknown()))
                                        .optional()
                                        .describe(
                                            'Property filters the occurrence must also match; standard PostHog property filter shapes.'
                                        ),
                                })
                                .describe(
                                    'Mirrors `moments.MomentEvent` for OpenAPI generation; writes validate via the pydantic model.'
                                )
                        )
                        .describe('Focus events (1-10); a moment is scanned around each occurrence of any of them.'),
                    before_seconds: zod
                        .number()
                        .min(visionScannersPartialUpdateBodyMomentsConfigOneBeforeSecondsMin)
                        .max(visionScannersPartialUpdateBodyMomentsConfigOneBeforeSecondsMax)
                        .optional()
                        .describe('Clip seconds included before the focus event. Defaults to 60.'),
                    after_seconds: zod
                        .number()
                        .min(visionScannersPartialUpdateBodyMomentsConfigOneAfterSecondsMin)
                        .max(visionScannersPartialUpdateBodyMomentsConfigOneAfterSecondsMax)
                        .optional()
                        .describe('Clip seconds included after the focus event. Defaults to 60.'),
                })
                .describe(
                    'Mirrors `moments.MomentsConfig` for OpenAPI generation; writes validate via the pydantic model.'
                ),
            zod.null(),
            zod.null(),
        ])
        .optional()
        .describe(
            'For moments-scoped scanners: the focus events (name + optional property filters) and clip bounds (`before_seconds`\/`after_seconds`, 5-300 each, defaulting to 60). Must be null for recording-scoped scanners.'
        ),
    provider: zod
        .enum(['google'])
        .describe('\* `google` - Google')
        .optional()
        .describe('LLM provider. v1 is Google-only.\n\n\* `google` - Google'),
    model: zod
        .enum(['gemini-3-flash-preview', 'gemini-3.1-flash-lite-preview'])
        .describe(
            '\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite'
        )
        .optional()
        .describe(
            'Concrete model to use for this scanner.\n\n\* `gemini-3-flash-preview` - Gemini 3 Flash\n\* `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite'
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
 * Estimate the observation volume a proposed scanner would generate, for the pre-save cost preview.
 */
export const visionScannersEstimateCreateBodySamplingRateDefault = 1
export const visionScannersEstimateCreateBodySamplingRateMin = 0
export const visionScannersEstimateCreateBodySamplingRateMax = 1

export const visionScannersEstimateCreateBodyMomentsConfigOneEventsItemEventMax = 400

export const visionScannersEstimateCreateBodyMomentsConfigOneBeforeSecondsMin = 5
export const visionScannersEstimateCreateBodyMomentsConfigOneBeforeSecondsMax = 300

export const visionScannersEstimateCreateBodyMomentsConfigOneAfterSecondsMin = 5
export const visionScannersEstimateCreateBodyMomentsConfigOneAfterSecondsMax = 300

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
        scanner_id: zod
            .uuid()
            .nullish()
            .describe(
                "The scanner being edited, excluded from `other_enabled_scanners_monthly` so its stored estimate isn't double-counted in the forecast. Omit (or null) when estimating a brand-new scanner."
            ),
        moments_config: zod
            .union([
                zod
                    .object({
                        events: zod
                            .array(
                                zod
                                    .object({
                                        event: zod
                                            .string()
                                            .max(visionScannersEstimateCreateBodyMomentsConfigOneEventsItemEventMax)
                                            .describe('Event name whose occurrences anchor moments.'),
                                        properties: zod
                                            .array(zod.record(zod.string(), zod.unknown()))
                                            .optional()
                                            .describe(
                                                'Property filters the occurrence must also match; standard PostHog property filter shapes.'
                                            ),
                                    })
                                    .describe(
                                        'Mirrors `moments.MomentEvent` for OpenAPI generation; writes validate via the pydantic model.'
                                    )
                            )
                            .describe(
                                'Focus events (1-10); a moment is scanned around each occurrence of any of them.'
                            ),
                        before_seconds: zod
                            .number()
                            .min(visionScannersEstimateCreateBodyMomentsConfigOneBeforeSecondsMin)
                            .max(visionScannersEstimateCreateBodyMomentsConfigOneBeforeSecondsMax)
                            .optional()
                            .describe('Clip seconds included before the focus event. Defaults to 60.'),
                        after_seconds: zod
                            .number()
                            .min(visionScannersEstimateCreateBodyMomentsConfigOneAfterSecondsMin)
                            .max(visionScannersEstimateCreateBodyMomentsConfigOneAfterSecondsMax)
                            .optional()
                            .describe('Clip seconds included after the focus event. Defaults to 60.'),
                    })
                    .describe(
                        'Mirrors `moments.MomentsConfig` for OpenAPI generation; writes validate via the pydantic model.'
                    ),
                zod.null(),
                zod.null(),
            ])
            .optional()
            .describe(
                'Proposed moments scope config. When set, the estimate counts moments (focus-event occurrences, capped per session) instead of whole sessions. Omit (or null) for recording scope.'
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
