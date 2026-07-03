/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 12 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Read-only access to a session's observations across every scanner the caller can read, for the replay-page dock.
 */
export const VisionObservationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const VisionObservationsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .string()
        .optional()
        .describe(
            'Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.'
        ),
    session_id: zod.string().describe('Session recording id to return observations for.'),
})

/**
 * Read-only access to a session's observations across every scanner the caller can read, for the replay-page dock.
 */
export const VisionObservationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EnvironmentVisionQuotaRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const VisionScannersListQueryParams = /* @__PURE__ */ zod.object({
    created_by: zod.string().optional().describe('Filter to scanners created by the given user IDs (comma-separated).'),
    emits_signals: zod.boolean().optional().describe('Filter to scanners that emit Signals.'),
    enabled: zod
        .string()
        .optional()
        .describe('Filter by enabled state. Accepts a comma-separated list of `enabled`/`disabled`.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .string()
        .optional()
        .describe(
            'Sort scanners by name, created_at, updated_at, scanner_type, enabled, sampling_rate, or created_by. Prefix with `-` for descending.'
        ),
    scanner_type: zod
        .string()
        .optional()
        .describe('Filter by scanner type (monitor, classifier, scorer, summarizer). Accepts a comma-separated list.'),
    search: zod
        .string()
        .optional()
        .describe('Case-insensitive substring match across name, description, and the prompt in scanner_config.'),
})

/**
 * CRUD for Replay Vision scanners.
 */
export const VisionScannersCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
            '* `monitor` - Monitor\n* `classifier` - Classifier\n* `scorer` - Scorer\n* `summarizer` - Summarizer'
        )
        .describe(
            'What the scanner does: monitor, classifier, scorer, or summarizer.\n\n* `monitor` - Monitor\n* `classifier` - Classifier\n* `scorer` - Scorer\n* `summarizer` - Summarizer'
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
            'Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`/`date_to` are stripped on save — the schedule controls time, not the user.'
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
        .describe('* `recording` - Entire recording\n* `moments` - Moments around events')
        .optional()
        .describe(
            'How much of each matched recording the scanner watches: `recording` scans the whole recording; `moments` scans short clips around each occurrence of the focus events. Fixed after creation.\n\n* `recording` - Entire recording\n* `moments` - Moments around events'
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
            'For moments-scoped scanners: the focus events (name + optional property filters) and clip bounds (`before_seconds`/`after_seconds`, 5-300 each, defaulting to 60). Must be null for recording-scoped scanners.'
        ),
    provider: zod
        .enum(['google'])
        .describe('* `google` - Google')
        .optional()
        .describe('LLM provider. v1 is Google-only.\n\n* `google` - Google'),
    model: zod
        .enum(['gemini-3-flash-preview', 'gemini-3.1-flash-lite-preview'])
        .describe(
            '* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite'
        )
        .describe(
            'Concrete model to use for this scanner.\n\n* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite'
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
export const VisionScannersRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
            '* `monitor` - Monitor\n* `classifier` - Classifier\n* `scorer` - Scorer\n* `summarizer` - Summarizer'
        )
        .optional()
        .describe(
            'What the scanner does: monitor, classifier, scorer, or summarizer.\n\n* `monitor` - Monitor\n* `classifier` - Classifier\n* `scorer` - Scorer\n* `summarizer` - Summarizer'
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
            'Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`/`date_to` are stripped on save — the schedule controls time, not the user.'
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
        .describe('* `recording` - Entire recording\n* `moments` - Moments around events')
        .optional()
        .describe(
            'How much of each matched recording the scanner watches: `recording` scans the whole recording; `moments` scans short clips around each occurrence of the focus events. Fixed after creation.\n\n* `recording` - Entire recording\n* `moments` - Moments around events'
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
            'For moments-scoped scanners: the focus events (name + optional property filters) and clip bounds (`before_seconds`/`after_seconds`, 5-300 each, defaulting to 60). Must be null for recording-scoped scanners.'
        ),
    provider: zod
        .enum(['google'])
        .describe('* `google` - Google')
        .optional()
        .describe('LLM provider. v1 is Google-only.\n\n* `google` - Google'),
    model: zod
        .enum(['gemini-3-flash-preview', 'gemini-3.1-flash-lite-preview'])
        .describe(
            '* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite'
        )
        .optional()
        .describe(
            'Concrete model to use for this scanner.\n\n* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.1-flash-lite-preview` - Gemini 3 Flash Lite'
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
export const VisionScannersDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Apply this scanner to one specific session, on demand. Returns 202 with the workflow handle.
 */
export const VisionScannersObserveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
    .describe('Body of POST /vision/scanners/{id}/observe/.')

/**
 * Read-only access to observations produced by a scanner.
 */
export const VisionScannersObservationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersObservationsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .string()
        .optional()
        .describe(
            'Sort observations. Plain keys: created_at, started_at, completed_at, status, recording_subject_email. JSONB keys: result_score (scorer), result_verdict (monitor), scanner_version. Prefix with `-` for descending; nullable keys sort nulls last either way.'
        ),
    recording_subject: zod
        .string()
        .optional()
        .describe('Filter to observations whose recording subject email contains this value (case-insensitive).'),
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
        .describe('Filter by trigger source (schedule or on_demand). Accepts a comma-separated list.'),
    verdict: zod
        .string()
        .optional()
        .describe('Filter monitor observations by verdict. Accepts a comma-separated list (e.g. `yes,inconclusive`).'),
})

/**
 * Read-only access to observations produced by a scanner.
 */
export const VisionScannersObservationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const visionScannersEstimateCreateBodySamplingRateDefault = 1
export const visionScannersEstimateCreateBodySamplingRateMin = 0
export const visionScannersEstimateCreateBodySamplingRateMax = 1

export const VisionScannersEstimateCreateBody = /* @__PURE__ */ zod
    .object({
        query: zod
            .unknown()
            .optional()
            .describe(
                'Proposed `RecordingsQuery` for the candidate filter. `date_from`/`date_to` are ignored — the estimate always uses a fixed 30-day lookback. Omit to estimate against all recordings.'
            ),
        sampling_rate: zod
            .number()
            .min(visionScannersEstimateCreateBodySamplingRateMin)
            .max(visionScannersEstimateCreateBodySamplingRateMax)
            .default(visionScannersEstimateCreateBodySamplingRateDefault)
            .describe('0..1 downsample applied to matched sessions. Defaults to 1.0 (no downsampling).'),
        scanner_id: zod
            .string()
            .nullish()
            .describe(
                "The scanner being edited, excluded from `other_enabled_scanners_monthly` so its stored estimate isn't double-counted in the forecast. Omit (or null) when estimating a brand-new scanner."
            ),
    })
    .describe('Body of POST /vision/scanners/estimate/ — a proposed, unsaved scanner config.')
