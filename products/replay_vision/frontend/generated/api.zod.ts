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
 * CRUD for Replay Vision scanners.
 */
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
            '\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer\n\* `indexer` - Indexer'
        )
        .describe(
            'What the scanner does: monitor, classifier, scorer, summarizer, or indexer.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer\n\* `indexer` - Indexer'
        ),
    scanner_config: zod
        .unknown()
        .describe(
            'Type-specific configuration. Monitor\/classifier\/scorer\/summarizer require `prompt`; classifiers add `tags`, scorers add `scale`. Indexer is fixed-task and rejects `prompt`.'
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
        .describe('0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling).'),
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
            '\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer\n\* `indexer` - Indexer'
        )
        .optional()
        .describe(
            'What the scanner does: monitor, classifier, scorer, summarizer, or indexer.\n\n\* `monitor` - Monitor\n\* `classifier` - Classifier\n\* `scorer` - Scorer\n\* `summarizer` - Summarizer\n\* `indexer` - Indexer'
        ),
    scanner_config: zod
        .unknown()
        .optional()
        .describe(
            'Type-specific configuration. Monitor\/classifier\/scorer\/summarizer require `prompt`; classifiers add `tags`, scorers add `scale`. Indexer is fixed-task and rejects `prompt`.'
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
        .describe('0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling).'),
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
