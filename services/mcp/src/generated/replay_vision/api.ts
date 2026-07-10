/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 19 enabled ops
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
 * Retrieve one observation. Any list filters passed along (status, tags, order_by, …) scope the `previous_observation_id`/`next_observation_id` navigation to the matching, identically-ordered set — so prev/next from a filtered table stays within that filtered list.
 */
export const VisionObservationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const VisionObservationsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    labeled: zod
        .string()
        .optional()
        .describe(
            'When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.'
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
 * Set or update the observation's shared label: whether the scanner scored the session correctly, plus optional feedback on what it got wrong. One label per observation, shared across the team; these labels feed prompt improvement. Requires session recording edit access.
 */
export const VisionObservationsLabelCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay observation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
 * Remove the observation's shared label. Requires session recording edit access.
 */
export const VisionObservationsLabelDestroyParams = /* @__PURE__ */ zod.object({
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
    sampling_mode: zod
        .enum(['focused', 'balanced', 'comprehensive'])
        .describe('* `focused` - Focused\n* `balanced` - Balanced\n* `comprehensive` - Comprehensive')
        .optional()
        .describe(
            'Quality pre-filter applied before random sampling. focused = top sessions only, balanced = drops the lowest-quality, comprehensive = no filter (default).\n\n* `focused` - Focused\n* `balanced` - Balanced\n* `comprehensive` - Comprehensive'
        ),
    provider: zod
        .enum(['google'])
        .describe('* `google` - Google')
        .optional()
        .describe('LLM provider. v1 is Google-only.\n\n* `google` - Google'),
    model: zod
        .enum(['gemini-2.5-flash', 'gemini-3-flash-preview', 'gemini-3.5-flash'])
        .describe(
            '* `gemini-2.5-flash` - Gemini 2.5 Flash\n* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.5-flash` - Gemini 3.5 Flash'
        )
        .describe(
            'Concrete model to use for this scanner.\n\n* `gemini-2.5-flash` - Gemini 2.5 Flash\n* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.5-flash` - Gemini 3.5 Flash'
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
    sampling_mode: zod
        .enum(['focused', 'balanced', 'comprehensive'])
        .describe('* `focused` - Focused\n* `balanced` - Balanced\n* `comprehensive` - Comprehensive')
        .optional()
        .describe(
            'Quality pre-filter applied before random sampling. focused = top sessions only, balanced = drops the lowest-quality, comprehensive = no filter (default).\n\n* `focused` - Focused\n* `balanced` - Balanced\n* `comprehensive` - Comprehensive'
        ),
    provider: zod
        .enum(['google'])
        .describe('* `google` - Google')
        .optional()
        .describe('LLM provider. v1 is Google-only.\n\n* `google` - Google'),
    model: zod
        .enum(['gemini-2.5-flash', 'gemini-3-flash-preview', 'gemini-3.5-flash'])
        .describe(
            '* `gemini-2.5-flash` - Gemini 2.5 Flash\n* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.5-flash` - Gemini 3.5 Flash'
        )
        .optional()
        .describe(
            'Concrete model to use for this scanner.\n\n* `gemini-2.5-flash` - Gemini 2.5 Flash\n* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.5-flash` - Gemini 3.5 Flash'
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
    labeled: zod
        .boolean()
        .optional()
        .describe(
            'When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.'
        ),
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
 * Aggregate counts and per-scanner-type distributions over the filtered observation set. Same filters as the list endpoint apply.
 */
export const VisionScannersObservationsStatsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    scanner_id: zod.string(),
})

export const VisionScannersObservationsStatsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    labeled: zod
        .string()
        .optional()
        .describe(
            'When true, return only observations that have a shared label (thumbs up or down); when false, only unlabeled observations.'
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
 * Apply this suggestion: write its prompt to the scanner (bumping the scanner version) and mark the suggestion applied. Only the current pending suggestion can be applied. Requires session recording edit access.
 */
export const VisionScannersPromptSuggestionsApplyCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner prompt suggestion.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    scanner_id: zod.string(),
})

/**
 * Dismiss this suggestion without applying it. Only the current pending suggestion can be dismissed. Requires session recording edit access.
 */
export const VisionScannersPromptSuggestionsDismissCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this replay scanner prompt suggestion.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    scanner_id: zod.string(),
})

/**
 * Generate a fresh prompt suggestion from the team's current ratings. The previous pending suggestion becomes history (superseded). Requires at least one rated observation and session recording edit access.
 */
export const VisionScannersPromptSuggestionsGenerateCreateParams = /* @__PURE__ */ zod.object({
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

export const visionScannersEstimateCreateBodySamplingModeDefault = `comprehensive`
export const visionScannersEstimateCreateBodyModelDefault = `gemini-3-flash-preview`

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
        sampling_mode: zod
            .enum(['focused', 'balanced', 'comprehensive'])
            .describe('* `focused` - Focused\n* `balanced` - Balanced\n* `comprehensive` - Comprehensive')
            .default(visionScannersEstimateCreateBodySamplingModeDefault)
            .describe(
                "Quality pre-filter applied to the matched-session count, mirroring the sweep's candidate query. Defaults to comprehensive (no filter).\n\n* `focused` - Focused\n* `balanced` - Balanced\n* `comprehensive` - Comprehensive"
            ),
        scanner_id: zod
            .string()
            .nullish()
            .describe(
                "The scanner being edited, excluded from `other_enabled_scanners_monthly_credits` so its stored estimate isn't double-counted in the forecast. Omit (or null) when estimating a brand-new scanner."
            ),
        model: zod
            .enum(['gemini-2.5-flash', 'gemini-3-flash-preview', 'gemini-3.5-flash'])
            .describe(
                '* `gemini-2.5-flash` - Gemini 2.5 Flash\n* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.5-flash` - Gemini 3.5 Flash'
            )
            .default(visionScannersEstimateCreateBodyModelDefault)
            .describe(
                'Proposed model; determines `credits_per_observation` in the response.\n\n* `gemini-2.5-flash` - Gemini 2.5 Flash\n* `gemini-3-flash-preview` - Gemini 3 Flash\n* `gemini-3.5-flash` - Gemini 3.5 Flash'
            ),
    })
    .describe('Body of POST /vision/scanners/estimate/ — a proposed, unsaved scanner config.')
