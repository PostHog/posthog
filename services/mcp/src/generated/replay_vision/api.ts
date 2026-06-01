/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 8 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

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
    emits_signals: zod.boolean().optional().describe('Filter to scanners that emit Signals.'),
    enabled: zod.boolean().optional().describe('Filter to enabled vs disabled scanners.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .array(zod.string())
        .optional()
        .describe(
            'Sort scanners by name, created_at, updated_at, or scanner_type. Prefix with `-` for descending.\n\n* `name` - Name\n* `-name` - Name (descending)\n* `created_at` - Created at\n* `-created_at` - Created at (descending)\n* `updated_at` - Updated at\n* `-updated_at` - Updated at (descending)\n* `scanner_type` - Scanner type\n* `-scanner_type` - Scanner type (descending)'
        ),
    scanner_type: zod
        .enum(['classifier', 'indexer', 'monitor', 'scorer', 'summarizer'])
        .optional()
        .describe(
            'Filter by scanner type (monitor, classifier, scorer, summarizer, indexer).\n\n* `monitor` - Monitor\n* `classifier` - Classifier\n* `scorer` - Scorer\n* `summarizer` - Summarizer\n* `indexer` - Indexer'
        ),
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

export const visionScannersCreateBodySamplingRateMin = 0
export const visionScannersCreateBodySamplingRateMax = 1

export const VisionScannersCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(visionScannersCreateBodyNameMax)
        .describe('Human-readable scanner name. Unique within the team.'),
    description: zod.string().optional().describe('Free-form description shown in the scanner management UI.'),
    scanner_type: zod
        .enum(['monitor', 'classifier', 'scorer', 'summarizer', 'indexer'])
        .describe(
            '* `monitor` - Monitor\n* `classifier` - Classifier\n* `scorer` - Scorer\n* `summarizer` - Summarizer\n* `indexer` - Indexer'
        )
        .describe(
            'What the scanner does: monitor, classifier, scorer, summarizer, or indexer.\n\n* `monitor` - Monitor\n* `classifier` - Classifier\n* `scorer` - Scorer\n* `summarizer` - Summarizer\n* `indexer` - Indexer'
        ),
    scanner_config: zod
        .unknown()
        .describe(
            'Type-specific configuration. Monitor/classifier/scorer/summarizer require `prompt`; classifiers add `tags`, scorers add `scale`. Indexer is fixed-task and rejects `prompt`.'
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
        .describe('0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling).'),
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

export const visionScannersPartialUpdateBodySamplingRateMin = 0
export const visionScannersPartialUpdateBodySamplingRateMax = 1

export const VisionScannersPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(visionScannersPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable scanner name. Unique within the team.'),
    description: zod.string().optional().describe('Free-form description shown in the scanner management UI.'),
    scanner_type: zod
        .enum(['monitor', 'classifier', 'scorer', 'summarizer', 'indexer'])
        .describe(
            '* `monitor` - Monitor\n* `classifier` - Classifier\n* `scorer` - Scorer\n* `summarizer` - Summarizer\n* `indexer` - Indexer'
        )
        .optional()
        .describe(
            'What the scanner does: monitor, classifier, scorer, summarizer, or indexer.\n\n* `monitor` - Monitor\n* `classifier` - Classifier\n* `scorer` - Scorer\n* `summarizer` - Summarizer\n* `indexer` - Indexer'
        ),
    scanner_config: zod
        .unknown()
        .optional()
        .describe(
            'Type-specific configuration. Monitor/classifier/scorer/summarizer require `prompt`; classifiers add `tags`, scorers add `scale`. Indexer is fixed-task and rejects `prompt`.'
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
        .describe('0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling).'),
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
        .array(zod.string())
        .optional()
        .describe(
            'Sort observations by created_at, started_at, completed_at, or status. Prefix with `-` for descending.\n\n* `created_at` - Created at\n* `-created_at` - Created at (descending)\n* `started_at` - Started at\n* `-started_at` - Started at (descending)\n* `completed_at` - Completed at\n* `-completed_at` - Completed at (descending)\n* `status` - Status\n* `-status` - Status (descending)'
        ),
    session_id: zod.string().optional().describe('Filter to observations of a specific session recording.'),
    status: zod
        .enum(['failed', 'ineligible', 'pending', 'running', 'succeeded'])
        .optional()
        .describe(
            'Filter by observation status.\n\n* `pending` - Pending\n* `running` - Running\n* `succeeded` - Succeeded\n* `failed` - Failed\n* `ineligible` - Ineligible'
        ),
    triggered_by: zod
        .enum(['on_demand', 'schedule'])
        .optional()
        .describe(
            'Filter by trigger source (schedule or on_demand).\n\n* `schedule` - Schedule\n* `on_demand` - On demand'
        ),
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
