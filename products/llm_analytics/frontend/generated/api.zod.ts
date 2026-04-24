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
 * Create a new evaluation run.

This endpoint validates the request and enqueues a Temporal workflow
to asynchronously execute the evaluation.
 */
export const evaluationRunsCreateBodyEventDefault = `$ai_generation`

export const EvaluationRunsCreateBody = /* @__PURE__ */ zod.object({
    evaluation_id: zod.uuid().describe('UUID of the evaluation to run.'),
    target_event_id: zod.uuid().describe('UUID of the $ai_generation event to evaluate.'),
    timestamp: zod.iso
        .datetime({})
        .describe('ISO 8601 timestamp of the target event (needed for efficient ClickHouse lookup).'),
    event: zod
        .string()
        .default(evaluationRunsCreateBodyEventDefault)
        .describe("Event name. Defaults to '$ai_generation'."),
    distinct_id: zod.string().nullish().describe('Distinct ID of the event (optional, improves lookup performance).'),
})

export const evaluationsCreateBodyNameMax = 400

export const evaluationsCreateBodyOutputConfigAllowsNaDefault = false
export const evaluationsCreateBodyModelConfigurationOneModelMax = 100

export const EvaluationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(evaluationsCreateBodyNameMax).describe('Name of the evaluation.'),
    description: zod.string().optional().describe('Optional description of what this evaluation checks.'),
    enabled: zod
        .boolean()
        .optional()
        .describe('Whether the evaluation runs automatically on new $ai_generation events.'),
    evaluation_type: zod
        .enum(['llm_judge', 'hog'])
        .describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog')
        .describe(
            "'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code.\n\n* `llm_judge` - LLM as a judge\n* `hog` - Hog"
        ),
    evaluation_config: zod
        .union([
            zod.object({
                prompt: zod
                    .string()
                    .min(1)
                    .describe('Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.'),
            }),
            zod.object({
                source: zod
                    .string()
                    .min(1)
                    .describe('Hog source code. Must return true (pass), false (fail), or null for N/A.'),
            }),
        ])
        .optional()
        .describe("Configuration dict. For 'llm_judge': {prompt}. For 'hog': {source}."),
    output_type: zod
        .enum(['boolean'])
        .describe('* `boolean` - Boolean (Pass/Fail)')
        .describe("Output format. Currently only 'boolean' is supported.\n\n* `boolean` - Boolean (Pass/Fail)"),
    output_config: zod
        .object({
            allows_na: zod
                .boolean()
                .default(evaluationsCreateBodyOutputConfigAllowsNaDefault)
                .describe('Whether the evaluation can return N/A for non-applicable generations.'),
        })
        .optional()
        .describe("Output config. For 'boolean' output_type: {allows_na} to permit N/A results."),
    conditions: zod
        .unknown()
        .optional()
        .describe(
            'Optional trigger conditions to filter which events are evaluated. OR between condition sets, AND within each.'
        ),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsCreateBodyModelConfigurationOneModelMax),
            provider_key_id: zod.uuid().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the evaluation.'),
})

export const evaluationsUpdateBodyNameMax = 400

export const evaluationsUpdateBodyOutputConfigAllowsNaDefault = false
export const evaluationsUpdateBodyModelConfigurationOneModelMax = 100

export const EvaluationsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(evaluationsUpdateBodyNameMax).describe('Name of the evaluation.'),
    description: zod.string().optional().describe('Optional description of what this evaluation checks.'),
    enabled: zod
        .boolean()
        .optional()
        .describe('Whether the evaluation runs automatically on new $ai_generation events.'),
    evaluation_type: zod
        .enum(['llm_judge', 'hog'])
        .describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog')
        .describe(
            "'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code.\n\n* `llm_judge` - LLM as a judge\n* `hog` - Hog"
        ),
    evaluation_config: zod
        .union([
            zod.object({
                prompt: zod
                    .string()
                    .min(1)
                    .describe('Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.'),
            }),
            zod.object({
                source: zod
                    .string()
                    .min(1)
                    .describe('Hog source code. Must return true (pass), false (fail), or null for N/A.'),
            }),
        ])
        .optional()
        .describe("Configuration dict. For 'llm_judge': {prompt}. For 'hog': {source}."),
    output_type: zod
        .enum(['boolean'])
        .describe('* `boolean` - Boolean (Pass/Fail)')
        .describe("Output format. Currently only 'boolean' is supported.\n\n* `boolean` - Boolean (Pass/Fail)"),
    output_config: zod
        .object({
            allows_na: zod
                .boolean()
                .default(evaluationsUpdateBodyOutputConfigAllowsNaDefault)
                .describe('Whether the evaluation can return N/A for non-applicable generations.'),
        })
        .optional()
        .describe("Output config. For 'boolean' output_type: {allows_na} to permit N/A results."),
    conditions: zod
        .unknown()
        .optional()
        .describe(
            'Optional trigger conditions to filter which events are evaluated. OR between condition sets, AND within each.'
        ),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsUpdateBodyModelConfigurationOneModelMax),
            provider_key_id: zod.uuid().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the evaluation.'),
})

export const evaluationsPartialUpdateBodyNameMax = 400

export const evaluationsPartialUpdateBodyOutputConfigAllowsNaDefault = false
export const evaluationsPartialUpdateBodyModelConfigurationOneModelMax = 100

export const EvaluationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(evaluationsPartialUpdateBodyNameMax).optional().describe('Name of the evaluation.'),
    description: zod.string().optional().describe('Optional description of what this evaluation checks.'),
    enabled: zod
        .boolean()
        .optional()
        .describe('Whether the evaluation runs automatically on new $ai_generation events.'),
    evaluation_type: zod
        .enum(['llm_judge', 'hog'])
        .describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog')
        .optional()
        .describe(
            "'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code.\n\n* `llm_judge` - LLM as a judge\n* `hog` - Hog"
        ),
    evaluation_config: zod
        .union([
            zod.object({
                prompt: zod
                    .string()
                    .min(1)
                    .describe('Evaluation criteria for the LLM judge. Describe what makes a good vs bad response.'),
            }),
            zod.object({
                source: zod
                    .string()
                    .min(1)
                    .describe('Hog source code. Must return true (pass), false (fail), or null for N/A.'),
            }),
        ])
        .optional()
        .describe("Configuration dict. For 'llm_judge': {prompt}. For 'hog': {source}."),
    output_type: zod
        .enum(['boolean'])
        .describe('* `boolean` - Boolean (Pass/Fail)')
        .optional()
        .describe("Output format. Currently only 'boolean' is supported.\n\n* `boolean` - Boolean (Pass/Fail)"),
    output_config: zod
        .object({
            allows_na: zod
                .boolean()
                .default(evaluationsPartialUpdateBodyOutputConfigAllowsNaDefault)
                .describe('Whether the evaluation can return N/A for non-applicable generations.'),
        })
        .optional()
        .describe("Output config. For 'boolean' output_type: {allows_na} to permit N/A results."),
    conditions: zod
        .unknown()
        .optional()
        .describe(
            'Optional trigger conditions to filter which events are evaluated. OR between condition sets, AND within each.'
        ),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsPartialUpdateBodyModelConfigurationOneModelMax),
            provider_key_id: zod.uuid().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the evaluation.'),
})

/**
 * Test Hog evaluation code against sample events without saving.
 */

export const evaluationsTestHogCreateBodySampleCountDefault = 5
export const evaluationsTestHogCreateBodySampleCountMax = 10

export const evaluationsTestHogCreateBodyAllowsNaDefault = false

export const EvaluationsTestHogCreateBody = /* @__PURE__ */ zod.object({
    source: zod
        .string()
        .min(1)
        .describe('Hog source code to test. Must return a boolean (true = pass, false = fail) or null for N/A.'),
    sample_count: zod
        .number()
        .min(1)
        .max(evaluationsTestHogCreateBodySampleCountMax)
        .default(evaluationsTestHogCreateBodySampleCountDefault)
        .describe('Number of recent $ai_generation events to test against (1–10, default 5).'),
    allows_na: zod
        .boolean()
        .default(evaluationsTestHogCreateBodyAllowsNaDefault)
        .describe('Whether the evaluation can return N/A for non-applicable generations.'),
    conditions: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .optional()
        .describe('Optional trigger conditions to filter which events are sampled.'),
})

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const llmAnalyticsClusteringJobsCreateBodyNameMax = 100

export const LlmAnalyticsClusteringJobsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsClusteringJobsCreateBodyNameMax),
    analysis_level: zod
        .enum(['trace', 'generation', 'evaluation'])
        .describe('* `trace` - trace\n* `generation` - generation\n* `evaluation` - evaluation'),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
})

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const llmAnalyticsClusteringJobsUpdateBodyNameMax = 100

export const LlmAnalyticsClusteringJobsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsClusteringJobsUpdateBodyNameMax),
    analysis_level: zod
        .enum(['trace', 'generation', 'evaluation'])
        .describe('* `trace` - trace\n* `generation` - generation\n* `evaluation` - evaluation'),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
})

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const llmAnalyticsClusteringJobsPartialUpdateBodyNameMax = 100

export const LlmAnalyticsClusteringJobsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsClusteringJobsPartialUpdateBodyNameMax).optional(),
    analysis_level: zod
        .enum(['trace', 'generation', 'evaluation'])
        .optional()
        .describe('* `trace` - trace\n* `generation` - generation\n* `evaluation` - evaluation'),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
})

/**
 * Trigger a new clustering workflow run.

This endpoint validates the request parameters and starts a Temporal workflow
to perform trace clustering with the specified configuration.
 */
export const llmAnalyticsClusteringRunsCreateBodyLookbackDaysDefault = 7
export const llmAnalyticsClusteringRunsCreateBodyLookbackDaysMax = 90

export const llmAnalyticsClusteringRunsCreateBodyMaxSamplesDefault = 1500
export const llmAnalyticsClusteringRunsCreateBodyMaxSamplesMin = 20
export const llmAnalyticsClusteringRunsCreateBodyMaxSamplesMax = 10000

export const llmAnalyticsClusteringRunsCreateBodyEmbeddingNormalizationDefault = `none`
export const llmAnalyticsClusteringRunsCreateBodyDimensionalityReductionMethodDefault = `umap`
export const llmAnalyticsClusteringRunsCreateBodyDimensionalityReductionNdimsDefault = 100
export const llmAnalyticsClusteringRunsCreateBodyDimensionalityReductionNdimsMin = 2
export const llmAnalyticsClusteringRunsCreateBodyDimensionalityReductionNdimsMax = 500

export const llmAnalyticsClusteringRunsCreateBodyClusteringMethodDefault = `hdbscan`
export const llmAnalyticsClusteringRunsCreateBodyMinClusterSizeFractionDefault = 0.02
export const llmAnalyticsClusteringRunsCreateBodyMinClusterSizeFractionMin = 0.02
export const llmAnalyticsClusteringRunsCreateBodyMinClusterSizeFractionMax = 0.5

export const llmAnalyticsClusteringRunsCreateBodyHdbscanMinSamplesDefault = 5
export const llmAnalyticsClusteringRunsCreateBodyHdbscanMinSamplesMax = 100

export const llmAnalyticsClusteringRunsCreateBodyKmeansMinKDefault = 2
export const llmAnalyticsClusteringRunsCreateBodyKmeansMinKMin = 2
export const llmAnalyticsClusteringRunsCreateBodyKmeansMinKMax = 50

export const llmAnalyticsClusteringRunsCreateBodyKmeansMaxKDefault = 20
export const llmAnalyticsClusteringRunsCreateBodyKmeansMaxKMin = 2
export const llmAnalyticsClusteringRunsCreateBodyKmeansMaxKMax = 100

export const llmAnalyticsClusteringRunsCreateBodyRunLabelDefault = ``
export const llmAnalyticsClusteringRunsCreateBodyRunLabelMax = 50

export const llmAnalyticsClusteringRunsCreateBodyVisualizationMethodDefault = `umap`

export const LlmAnalyticsClusteringRunsCreateBody = /* @__PURE__ */ zod
    .object({
        lookback_days: zod
            .number()
            .min(1)
            .max(llmAnalyticsClusteringRunsCreateBodyLookbackDaysMax)
            .default(llmAnalyticsClusteringRunsCreateBodyLookbackDaysDefault)
            .describe('Number of days to look back for traces'),
        max_samples: zod
            .number()
            .min(llmAnalyticsClusteringRunsCreateBodyMaxSamplesMin)
            .max(llmAnalyticsClusteringRunsCreateBodyMaxSamplesMax)
            .default(llmAnalyticsClusteringRunsCreateBodyMaxSamplesDefault)
            .describe('Maximum number of traces to sample for clustering'),
        embedding_normalization: zod
            .enum(['none', 'l2'])
            .describe('* `none` - none\n* `l2` - l2')
            .default(llmAnalyticsClusteringRunsCreateBodyEmbeddingNormalizationDefault)
            .describe(
                "Embedding normalization method: 'none' (raw embeddings) or 'l2' (L2 normalize before clustering)\n\n* `none` - none\n* `l2` - l2"
            ),
        dimensionality_reduction_method: zod
            .enum(['none', 'umap', 'pca'])
            .describe('* `none` - none\n* `umap` - umap\n* `pca` - pca')
            .default(llmAnalyticsClusteringRunsCreateBodyDimensionalityReductionMethodDefault)
            .describe(
                "Dimensionality reduction method: 'none' (cluster on raw), 'umap', or 'pca'\n\n* `none` - none\n* `umap` - umap\n* `pca` - pca"
            ),
        dimensionality_reduction_ndims: zod
            .number()
            .min(llmAnalyticsClusteringRunsCreateBodyDimensionalityReductionNdimsMin)
            .max(llmAnalyticsClusteringRunsCreateBodyDimensionalityReductionNdimsMax)
            .default(llmAnalyticsClusteringRunsCreateBodyDimensionalityReductionNdimsDefault)
            .describe("Target dimensions for dimensionality reduction (ignored if method is 'none')"),
        clustering_method: zod
            .enum(['hdbscan', 'kmeans'])
            .describe('* `hdbscan` - hdbscan\n* `kmeans` - kmeans')
            .default(llmAnalyticsClusteringRunsCreateBodyClusteringMethodDefault)
            .describe(
                "Clustering algorithm: 'hdbscan' (density-based, auto-determines k) or 'kmeans' (centroid-based)\n\n* `hdbscan` - hdbscan\n* `kmeans` - kmeans"
            ),
        min_cluster_size_fraction: zod
            .number()
            .min(llmAnalyticsClusteringRunsCreateBodyMinClusterSizeFractionMin)
            .max(llmAnalyticsClusteringRunsCreateBodyMinClusterSizeFractionMax)
            .default(llmAnalyticsClusteringRunsCreateBodyMinClusterSizeFractionDefault)
            .describe('Minimum cluster size as fraction of total samples (e.g., 0.02 = 2%)'),
        hdbscan_min_samples: zod
            .number()
            .min(1)
            .max(llmAnalyticsClusteringRunsCreateBodyHdbscanMinSamplesMax)
            .default(llmAnalyticsClusteringRunsCreateBodyHdbscanMinSamplesDefault)
            .describe('HDBSCAN min_samples parameter (higher = more conservative clustering)'),
        kmeans_min_k: zod
            .number()
            .min(llmAnalyticsClusteringRunsCreateBodyKmeansMinKMin)
            .max(llmAnalyticsClusteringRunsCreateBodyKmeansMinKMax)
            .default(llmAnalyticsClusteringRunsCreateBodyKmeansMinKDefault)
            .describe('Minimum number of clusters to try for k-means'),
        kmeans_max_k: zod
            .number()
            .min(llmAnalyticsClusteringRunsCreateBodyKmeansMaxKMin)
            .max(llmAnalyticsClusteringRunsCreateBodyKmeansMaxKMax)
            .default(llmAnalyticsClusteringRunsCreateBodyKmeansMaxKDefault)
            .describe('Maximum number of clusters to try for k-means'),
        run_label: zod
            .string()
            .max(llmAnalyticsClusteringRunsCreateBodyRunLabelMax)
            .default(llmAnalyticsClusteringRunsCreateBodyRunLabelDefault)
            .describe('Optional label/tag for the clustering run (used as suffix in run_id for tracking experiments)'),
        visualization_method: zod
            .enum(['umap', 'pca', 'tsne'])
            .describe('* `umap` - umap\n* `pca` - pca\n* `tsne` - tsne')
            .default(llmAnalyticsClusteringRunsCreateBodyVisualizationMethodDefault)
            .describe(
                "Method for 2D scatter plot visualization: 'umap', 'pca', or 'tsne'\n\n* `umap` - umap\n* `pca` - pca\n* `tsne` - tsne"
            ),
        event_filters: zod
            .array(zod.record(zod.string(), zod.unknown()))
            .optional()
            .describe('Property filters to scope which traces are included in clustering (PostHog standard format)'),
        clustering_job_id: zod
            .uuid()
            .nullish()
            .describe(
                "If provided, use this clustering job's analysis_level and event_filters instead of request params"
            ),
    })
    .describe('Serializer for clustering workflow request parameters.')

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const llmAnalyticsEvaluationReportsCreateBodyTimezoneNameMax = 64

export const llmAnalyticsEvaluationReportsCreateBodyMaxSampleSizeMin = -2147483648
export const llmAnalyticsEvaluationReportsCreateBodyMaxSampleSizeMax = 2147483647

export const llmAnalyticsEvaluationReportsCreateBodyTriggerThresholdMin = -2147483648
export const llmAnalyticsEvaluationReportsCreateBodyTriggerThresholdMax = 2147483647

export const llmAnalyticsEvaluationReportsCreateBodyCooldownMinutesMin = -2147483648
export const llmAnalyticsEvaluationReportsCreateBodyCooldownMinutesMax = 2147483647

export const llmAnalyticsEvaluationReportsCreateBodyDailyRunCapMin = -2147483648
export const llmAnalyticsEvaluationReportsCreateBodyDailyRunCapMax = 2147483647

export const LlmAnalyticsEvaluationReportsCreateBody = /* @__PURE__ */ zod.object({
    evaluation: zod.uuid().describe('UUID of the evaluation this report config belongs to.'),
    frequency: zod
        .enum(['scheduled', 'every_n'])
        .describe('* `scheduled` - Scheduled\n* `every_n` - Every N')
        .optional()
        .describe(
            "'every_n' triggers a report after N evaluations run; 'scheduled' uses an rrule schedule.\n\n* `scheduled` - Scheduled\n* `every_n` - Every N"
        ),
    rrule: zod.string().optional().describe("RFC 5545 recurrence rule string. Required when frequency is 'scheduled'."),
    starts_at: zod.iso
        .datetime({})
        .nullish()
        .describe("Schedule start datetime (ISO 8601). Required when frequency is 'scheduled'."),
    timezone_name: zod
        .string()
        .max(llmAnalyticsEvaluationReportsCreateBodyTimezoneNameMax)
        .optional()
        .describe("IANA timezone name for scheduled delivery (e.g. 'America/New_York')."),
    delivery_targets: zod
        .unknown()
        .optional()
        .describe(
            "List of delivery targets. Each is {type: 'email', value: '...'} or {type: 'slack', integration_id: N, channel: '...'}."
        ),
    max_sample_size: zod
        .number()
        .min(llmAnalyticsEvaluationReportsCreateBodyMaxSampleSizeMin)
        .max(llmAnalyticsEvaluationReportsCreateBodyMaxSampleSizeMax)
        .optional()
        .describe('Max number of evaluation runs included in each report. Defaults to 100.'),
    enabled: zod.boolean().optional().describe('Whether report delivery is active.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete this report config.'),
    report_prompt_guidance: zod
        .string()
        .optional()
        .describe('Optional custom instructions injected into the AI report prompt to focus analysis.'),
    trigger_threshold: zod
        .number()
        .min(llmAnalyticsEvaluationReportsCreateBodyTriggerThresholdMin)
        .max(llmAnalyticsEvaluationReportsCreateBodyTriggerThresholdMax)
        .nullish()
        .describe('Number of evaluation runs that trigger a report (every_n mode). Min 10, max 1000.'),
    cooldown_minutes: zod
        .number()
        .min(llmAnalyticsEvaluationReportsCreateBodyCooldownMinutesMin)
        .max(llmAnalyticsEvaluationReportsCreateBodyCooldownMinutesMax)
        .optional()
        .describe('Minimum minutes between reports in every_n mode to prevent spam. Min 60, max 1440 (24 hours).'),
    daily_run_cap: zod
        .number()
        .min(llmAnalyticsEvaluationReportsCreateBodyDailyRunCapMin)
        .max(llmAnalyticsEvaluationReportsCreateBodyDailyRunCapMax)
        .optional()
        .describe('Max reports generated per day. Defaults to 3.'),
})

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const llmAnalyticsEvaluationReportsUpdateBodyTimezoneNameMax = 64

export const llmAnalyticsEvaluationReportsUpdateBodyMaxSampleSizeMin = -2147483648
export const llmAnalyticsEvaluationReportsUpdateBodyMaxSampleSizeMax = 2147483647

export const llmAnalyticsEvaluationReportsUpdateBodyTriggerThresholdMin = -2147483648
export const llmAnalyticsEvaluationReportsUpdateBodyTriggerThresholdMax = 2147483647

export const llmAnalyticsEvaluationReportsUpdateBodyCooldownMinutesMin = -2147483648
export const llmAnalyticsEvaluationReportsUpdateBodyCooldownMinutesMax = 2147483647

export const llmAnalyticsEvaluationReportsUpdateBodyDailyRunCapMin = -2147483648
export const llmAnalyticsEvaluationReportsUpdateBodyDailyRunCapMax = 2147483647

export const LlmAnalyticsEvaluationReportsUpdateBody = /* @__PURE__ */ zod.object({
    evaluation: zod.uuid().describe('UUID of the evaluation this report config belongs to.'),
    frequency: zod
        .enum(['scheduled', 'every_n'])
        .describe('* `scheduled` - Scheduled\n* `every_n` - Every N')
        .optional()
        .describe(
            "'every_n' triggers a report after N evaluations run; 'scheduled' uses an rrule schedule.\n\n* `scheduled` - Scheduled\n* `every_n` - Every N"
        ),
    rrule: zod.string().optional().describe("RFC 5545 recurrence rule string. Required when frequency is 'scheduled'."),
    starts_at: zod.iso
        .datetime({})
        .nullish()
        .describe("Schedule start datetime (ISO 8601). Required when frequency is 'scheduled'."),
    timezone_name: zod
        .string()
        .max(llmAnalyticsEvaluationReportsUpdateBodyTimezoneNameMax)
        .optional()
        .describe("IANA timezone name for scheduled delivery (e.g. 'America/New_York')."),
    delivery_targets: zod
        .unknown()
        .optional()
        .describe(
            "List of delivery targets. Each is {type: 'email', value: '...'} or {type: 'slack', integration_id: N, channel: '...'}."
        ),
    max_sample_size: zod
        .number()
        .min(llmAnalyticsEvaluationReportsUpdateBodyMaxSampleSizeMin)
        .max(llmAnalyticsEvaluationReportsUpdateBodyMaxSampleSizeMax)
        .optional()
        .describe('Max number of evaluation runs included in each report. Defaults to 100.'),
    enabled: zod.boolean().optional().describe('Whether report delivery is active.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete this report config.'),
    report_prompt_guidance: zod
        .string()
        .optional()
        .describe('Optional custom instructions injected into the AI report prompt to focus analysis.'),
    trigger_threshold: zod
        .number()
        .min(llmAnalyticsEvaluationReportsUpdateBodyTriggerThresholdMin)
        .max(llmAnalyticsEvaluationReportsUpdateBodyTriggerThresholdMax)
        .nullish()
        .describe('Number of evaluation runs that trigger a report (every_n mode). Min 10, max 1000.'),
    cooldown_minutes: zod
        .number()
        .min(llmAnalyticsEvaluationReportsUpdateBodyCooldownMinutesMin)
        .max(llmAnalyticsEvaluationReportsUpdateBodyCooldownMinutesMax)
        .optional()
        .describe('Minimum minutes between reports in every_n mode to prevent spam. Min 60, max 1440 (24 hours).'),
    daily_run_cap: zod
        .number()
        .min(llmAnalyticsEvaluationReportsUpdateBodyDailyRunCapMin)
        .max(llmAnalyticsEvaluationReportsUpdateBodyDailyRunCapMax)
        .optional()
        .describe('Max reports generated per day. Defaults to 3.'),
})

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const llmAnalyticsEvaluationReportsPartialUpdateBodyTimezoneNameMax = 64

export const llmAnalyticsEvaluationReportsPartialUpdateBodyMaxSampleSizeMin = -2147483648
export const llmAnalyticsEvaluationReportsPartialUpdateBodyMaxSampleSizeMax = 2147483647

export const llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMin = -2147483648
export const llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMax = 2147483647

export const llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMin = -2147483648
export const llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMax = 2147483647

export const llmAnalyticsEvaluationReportsPartialUpdateBodyDailyRunCapMin = -2147483648
export const llmAnalyticsEvaluationReportsPartialUpdateBodyDailyRunCapMax = 2147483647

export const LlmAnalyticsEvaluationReportsPartialUpdateBody = /* @__PURE__ */ zod.object({
    evaluation: zod.uuid().optional().describe('UUID of the evaluation this report config belongs to.'),
    frequency: zod
        .enum(['scheduled', 'every_n'])
        .describe('* `scheduled` - Scheduled\n* `every_n` - Every N')
        .optional()
        .describe(
            "'every_n' triggers a report after N evaluations run; 'scheduled' uses an rrule schedule.\n\n* `scheduled` - Scheduled\n* `every_n` - Every N"
        ),
    rrule: zod.string().optional().describe("RFC 5545 recurrence rule string. Required when frequency is 'scheduled'."),
    starts_at: zod.iso
        .datetime({})
        .nullish()
        .describe("Schedule start datetime (ISO 8601). Required when frequency is 'scheduled'."),
    timezone_name: zod
        .string()
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyTimezoneNameMax)
        .optional()
        .describe("IANA timezone name for scheduled delivery (e.g. 'America/New_York')."),
    delivery_targets: zod
        .unknown()
        .optional()
        .describe(
            "List of delivery targets. Each is {type: 'email', value: '...'} or {type: 'slack', integration_id: N, channel: '...'}."
        ),
    max_sample_size: zod
        .number()
        .min(llmAnalyticsEvaluationReportsPartialUpdateBodyMaxSampleSizeMin)
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyMaxSampleSizeMax)
        .optional()
        .describe('Max number of evaluation runs included in each report. Defaults to 100.'),
    enabled: zod.boolean().optional().describe('Whether report delivery is active.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete this report config.'),
    report_prompt_guidance: zod
        .string()
        .optional()
        .describe('Optional custom instructions injected into the AI report prompt to focus analysis.'),
    trigger_threshold: zod
        .number()
        .min(llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMin)
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMax)
        .nullish()
        .describe('Number of evaluation runs that trigger a report (every_n mode). Min 10, max 1000.'),
    cooldown_minutes: zod
        .number()
        .min(llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMin)
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMax)
        .optional()
        .describe('Minimum minutes between reports in every_n mode to prevent spam. Min 60, max 1440 (24 hours).'),
    daily_run_cap: zod
        .number()
        .min(llmAnalyticsEvaluationReportsPartialUpdateBodyDailyRunCapMin)
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyDailyRunCapMax)
        .optional()
        .describe('Max reports generated per day. Defaults to 3.'),
})

/**
 * 
Generate an AI-powered summary of evaluation results.

This endpoint analyzes evaluation runs and identifies patterns in passing
and failing evaluations, providing actionable recommendations.

Data is fetched server-side by evaluation ID to ensure data integrity.

**Use Cases:**
- Understand why evaluations are passing or failing
- Identify systematic issues in LLM responses
- Get recommendations for improving response quality
- Review patterns across many evaluation runs at once
        
 */
export const llmAnalyticsEvaluationSummaryCreateBodyFilterDefault = `all`
export const llmAnalyticsEvaluationSummaryCreateBodyGenerationIdsMax = 250

export const llmAnalyticsEvaluationSummaryCreateBodyForceRefreshDefault = false

export const LlmAnalyticsEvaluationSummaryCreateBody = /* @__PURE__ */ zod
    .object({
        evaluation_id: zod.uuid().describe('UUID of the evaluation config to summarize'),
        filter: zod
            .enum(['all', 'pass', 'fail', 'na'])
            .describe('* `all` - all\n* `pass` - pass\n* `fail` - fail\n* `na` - na')
            .default(llmAnalyticsEvaluationSummaryCreateBodyFilterDefault)
            .describe(
                "Filter type to apply ('all', 'pass', 'fail', or 'na')\n\n* `all` - all\n* `pass` - pass\n* `fail` - fail\n* `na` - na"
            ),
        generation_ids: zod
            .array(zod.uuid())
            .max(llmAnalyticsEvaluationSummaryCreateBodyGenerationIdsMax)
            .optional()
            .describe('Optional: specific generation IDs to include in summary (max 250)'),
        force_refresh: zod
            .boolean()
            .default(llmAnalyticsEvaluationSummaryCreateBodyForceRefreshDefault)
            .describe('If true, bypass cache and generate a fresh summary'),
    })
    .describe('Request serializer for evaluation summary - accepts IDs only, fetches data server-side.')

export const llmAnalyticsProviderKeysCreateBodyNameMax = 255

export const llmAnalyticsProviderKeysCreateBodySetAsActiveDefault = false

export const LlmAnalyticsProviderKeysCreateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysCreateBodyNameMax),
    api_key: zod.string().optional(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysCreateBodySetAsActiveDefault),
})

export const llmAnalyticsProviderKeysUpdateBodyNameMax = 255

export const llmAnalyticsProviderKeysUpdateBodySetAsActiveDefault = false

export const LlmAnalyticsProviderKeysUpdateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysUpdateBodyNameMax),
    api_key: zod.string().optional(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysUpdateBodySetAsActiveDefault),
})

export const llmAnalyticsProviderKeysPartialUpdateBodyNameMax = 255

export const llmAnalyticsProviderKeysPartialUpdateBodySetAsActiveDefault = false

export const LlmAnalyticsProviderKeysPartialUpdateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .optional()
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysPartialUpdateBodyNameMax).optional(),
    api_key: zod.string().optional(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysPartialUpdateBodySetAsActiveDefault),
})

/**
 * Assign this key to evaluations and optionally re-enable them.
 */
export const llmAnalyticsProviderKeysAssignCreateBodyNameMax = 255

export const llmAnalyticsProviderKeysAssignCreateBodySetAsActiveDefault = false

export const LlmAnalyticsProviderKeysAssignCreateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysAssignCreateBodyNameMax),
    api_key: zod.string().optional(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysAssignCreateBodySetAsActiveDefault),
})

export const llmAnalyticsProviderKeysValidateCreateBodyNameMax = 255

export const llmAnalyticsProviderKeysValidateCreateBodySetAsActiveDefault = false

export const LlmAnalyticsProviderKeysValidateCreateBody = /* @__PURE__ */ zod.object({
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysValidateCreateBodyNameMax),
    api_key: zod.string().optional(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysValidateCreateBodySetAsActiveDefault),
})

export const llmAnalyticsReviewQueueItemsCreateBodyTraceIdMax = 255

export const LlmAnalyticsReviewQueueItemsCreateBody = /* @__PURE__ */ zod.object({
    queue_id: zod.uuid().describe('Review queue ID that should own this pending trace.'),
    trace_id: zod
        .string()
        .max(llmAnalyticsReviewQueueItemsCreateBodyTraceIdMax)
        .describe('Trace ID to add to the selected review queue.'),
})

export const LlmAnalyticsReviewQueueItemsPartialUpdateBody = /* @__PURE__ */ zod.object({
    queue_id: zod.uuid().optional().describe('Review queue ID that should own this pending trace.'),
})

export const llmAnalyticsReviewQueuesCreateBodyNameMax = 255

export const LlmAnalyticsReviewQueuesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsReviewQueuesCreateBodyNameMax).describe('Human-readable queue name.'),
})

export const llmAnalyticsReviewQueuesPartialUpdateBodyNameMax = 255

export const LlmAnalyticsReviewQueuesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(llmAnalyticsReviewQueuesPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable queue name.'),
})

export const llmAnalyticsScoreDefinitionsCreateBodyNameMax = 255

export const llmAnalyticsScoreDefinitionsCreateBodyArchivedDefault = false
export const llmAnalyticsScoreDefinitionsCreateBodyConfigOneOneOptionsItemKeyMax = 128

export const llmAnalyticsScoreDefinitionsCreateBodyConfigOneOneOptionsItemLabelMax = 256

export const LlmAnalyticsScoreDefinitionsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsScoreDefinitionsCreateBodyNameMax).describe('Human-readable scorer name.'),
    description: zod.string().nullish().describe('Optional human-readable description.'),
    kind: zod
        .enum(['categorical', 'numeric', 'boolean'])
        .describe('* `categorical` - categorical\n* `numeric` - numeric\n* `boolean` - boolean')
        .describe(
            'Scorer kind. This cannot be changed after creation.\n\n* `categorical` - categorical\n* `numeric` - numeric\n* `boolean` - boolean'
        ),
    archived: zod
        .boolean()
        .default(llmAnalyticsScoreDefinitionsCreateBodyArchivedDefault)
        .describe('New scorers are always created as active.'),
    config: zod
        .union([
            zod.object({
                options: zod
                    .array(
                        zod.object({
                            key: zod
                                .string()
                                .max(llmAnalyticsScoreDefinitionsCreateBodyConfigOneOneOptionsItemKeyMax)
                                .describe(
                                    'Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'
                                ),
                            label: zod
                                .string()
                                .max(llmAnalyticsScoreDefinitionsCreateBodyConfigOneOneOptionsItemLabelMax)
                                .describe('Human-readable option label.'),
                        })
                    )
                    .describe('Ordered categorical options available to the scorer.'),
                selection_mode: zod
                    .enum(['single', 'multiple'])
                    .describe('* `single` - single\n* `multiple` - multiple')
                    .optional()
                    .describe(
                        'Whether reviewers can select one option or multiple options. Defaults to `single`.\n\n* `single` - single\n* `multiple` - multiple'
                    ),
                min_selections: zod
                    .number()
                    .min(1)
                    .nullish()
                    .describe(
                        'Optional minimum number of options that can be selected when `selection_mode` is `multiple`.'
                    ),
                max_selections: zod
                    .number()
                    .min(1)
                    .nullish()
                    .describe(
                        'Optional maximum number of options that can be selected when `selection_mode` is `multiple`.'
                    ),
            }),
            zod.object({
                min: zod.number().nullish().describe('Optional inclusive minimum score.'),
                max: zod.number().nullish().describe('Optional inclusive maximum score.'),
                step: zod
                    .number()
                    .nullish()
                    .describe('Optional increment step for numeric input, for example 1 or 0.5.'),
            }),
            zod.object({
                true_label: zod.string().optional().describe('Optional label for a true value.'),
                false_label: zod.string().optional().describe('Optional label for a false value.'),
            }),
        ])
        .describe('Initial immutable scorer configuration.'),
})

export const llmAnalyticsScoreDefinitionsPartialUpdateBodyNameMax = 255

export const LlmAnalyticsScoreDefinitionsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(llmAnalyticsScoreDefinitionsPartialUpdateBodyNameMax)
        .optional()
        .describe('Updated scorer name.'),
    description: zod.string().nullish().describe('Updated scorer description.'),
    archived: zod.boolean().optional().describe('Whether the scorer is archived.'),
})

export const llmAnalyticsScoreDefinitionsNewVersionCreateBodyConfigOneOneOptionsItemKeyMax = 128

export const llmAnalyticsScoreDefinitionsNewVersionCreateBodyConfigOneOneOptionsItemLabelMax = 256

export const LlmAnalyticsScoreDefinitionsNewVersionCreateBody = /* @__PURE__ */ zod.object({
    config: zod
        .union([
            zod.object({
                options: zod
                    .array(
                        zod.object({
                            key: zod
                                .string()
                                .max(llmAnalyticsScoreDefinitionsNewVersionCreateBodyConfigOneOneOptionsItemKeyMax)
                                .describe(
                                    'Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'
                                ),
                            label: zod
                                .string()
                                .max(llmAnalyticsScoreDefinitionsNewVersionCreateBodyConfigOneOneOptionsItemLabelMax)
                                .describe('Human-readable option label.'),
                        })
                    )
                    .describe('Ordered categorical options available to the scorer.'),
                selection_mode: zod
                    .enum(['single', 'multiple'])
                    .describe('* `single` - single\n* `multiple` - multiple')
                    .optional()
                    .describe(
                        'Whether reviewers can select one option or multiple options. Defaults to `single`.\n\n* `single` - single\n* `multiple` - multiple'
                    ),
                min_selections: zod
                    .number()
                    .min(1)
                    .nullish()
                    .describe(
                        'Optional minimum number of options that can be selected when `selection_mode` is `multiple`.'
                    ),
                max_selections: zod
                    .number()
                    .min(1)
                    .nullish()
                    .describe(
                        'Optional maximum number of options that can be selected when `selection_mode` is `multiple`.'
                    ),
            }),
            zod.object({
                min: zod.number().nullish().describe('Optional inclusive minimum score.'),
                max: zod.number().nullish().describe('Optional inclusive maximum score.'),
                step: zod
                    .number()
                    .nullish()
                    .describe('Optional increment step for numeric input, for example 1 or 0.5.'),
            }),
            zod.object({
                true_label: zod.string().optional().describe('Optional label for a true value.'),
                false_label: zod.string().optional().describe('Optional label for a false value.'),
            }),
        ])
        .describe('Next immutable scorer configuration.'),
})

export const llmAnalyticsSentimentCreateBodyIdsMax = 5

export const llmAnalyticsSentimentCreateBodyAnalysisLevelDefault = `trace`
export const llmAnalyticsSentimentCreateBodyForceRefreshDefault = false

export const LlmAnalyticsSentimentCreateBody = /* @__PURE__ */ zod.object({
    ids: zod.array(zod.string()).min(1).max(llmAnalyticsSentimentCreateBodyIdsMax),
    analysis_level: zod
        .enum(['trace', 'generation'])
        .describe('* `trace` - trace\n* `generation` - generation')
        .default(llmAnalyticsSentimentCreateBodyAnalysisLevelDefault),
    force_refresh: zod.boolean().default(llmAnalyticsSentimentCreateBodyForceRefreshDefault),
    date_from: zod.string().nullish(),
    date_to: zod.string().nullish(),
})

/**
 * 
Generate an AI-powered summary of an LLM trace or event.

This endpoint analyzes the provided trace/event, generates a line-numbered text
representation, and uses an LLM to create a concise summary with line references.

**Two ways to use this endpoint:**

1. **By ID (recommended):** Pass `trace_id` or `generation_id` with an optional `date_from`/`date_to`.
   The backend fetches the data automatically. `summarize_type` is inferred.
2. **By data:** Pass the full trace/event data blob in `data` with `summarize_type`.
   This is how the frontend uses it.

**Summary Format:**
- Title (concise, max 10 words)
- Mermaid flow diagram showing the main flow
- 3-10 summary bullets with line references
- "Interesting Notes" section for failures, successes, or unusual patterns
- Line references in [L45] or [L45-52] format pointing to relevant sections

The response includes the structured summary, the text representation, and metadata.
        
 */
export const llmAnalyticsSummarizationCreateBodyModeDefault = `minimal`
export const llmAnalyticsSummarizationCreateBodyForceRefreshDefault = false

export const LlmAnalyticsSummarizationCreateBody = /* @__PURE__ */ zod.object({
    summarize_type: zod
        .enum(['trace', 'event'])
        .describe('* `trace` - trace\n* `event` - event')
        .optional()
        .describe(
            'Type of entity to summarize. Inferred automatically when using trace_id or generation_id.\n\n* `trace` - trace\n* `event` - event'
        ),
    mode: zod
        .enum(['minimal', 'detailed'])
        .describe('* `minimal` - minimal\n* `detailed` - detailed')
        .default(llmAnalyticsSummarizationCreateBodyModeDefault)
        .describe(
            "Summary detail level: 'minimal' for 3-5 points, 'detailed' for 5-10 points\n\n* `minimal` - minimal\n* `detailed` - detailed"
        ),
    data: zod
        .unknown()
        .optional()
        .describe(
            'Data to summarize. For traces: {trace, hierarchy}. For events: {event}. Not required when using trace_id or generation_id.'
        ),
    force_refresh: zod
        .boolean()
        .default(llmAnalyticsSummarizationCreateBodyForceRefreshDefault)
        .describe('Force regenerate summary, bypassing cache'),
    model: zod.string().nullish().describe('LLM model to use (defaults based on provider)'),
    trace_id: zod
        .string()
        .optional()
        .describe(
            'Trace ID to summarize. The backend fetches the trace data automatically. Requires date_from for efficient lookup.'
        ),
    generation_id: zod
        .string()
        .optional()
        .describe(
            'Generation event UUID to summarize. The backend fetches the event data automatically. Requires date_from for efficient lookup.'
        ),
    date_from: zod
        .string()
        .nullish()
        .describe("Start of date range for ID-based lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d."),
    date_to: zod.string().nullish().describe('End of date range for ID-based lookup. Defaults to now.'),
})

/**
 * 
Check which traces have cached summaries available.

This endpoint allows batch checking of multiple trace IDs to see which ones
have cached summaries. Returns only the traces that have cached summaries
with their titles.

**Use Cases:**
- Load cached summaries on session view load
- Avoid unnecessary LLM calls for already-summarized traces
- Display summary previews without generating new summaries
        
 */
export const llmAnalyticsSummarizationBatchCheckCreateBodyTraceIdsMax = 100

export const llmAnalyticsSummarizationBatchCheckCreateBodyModeDefault = `minimal`

export const LlmAnalyticsSummarizationBatchCheckCreateBody = /* @__PURE__ */ zod.object({
    trace_ids: zod
        .array(zod.string())
        .max(llmAnalyticsSummarizationBatchCheckCreateBodyTraceIdsMax)
        .describe('List of trace IDs to check for cached summaries'),
    mode: zod
        .enum(['minimal', 'detailed'])
        .describe('* `minimal` - minimal\n* `detailed` - detailed')
        .default(llmAnalyticsSummarizationBatchCheckCreateBodyModeDefault)
        .describe('Summary detail level to check for\n\n* `minimal` - minimal\n* `detailed` - detailed'),
    model: zod.string().nullish().describe('LLM model used for cached summaries'),
})

/**
 * 
Generate a human-readable text representation of an LLM trace event.

This endpoint converts LLM analytics events ($ai_generation, $ai_span, $ai_embedding, or $ai_trace)
into formatted text representations suitable for display, logging, or analysis.

**Supported Event Types:**
- `$ai_generation`: Individual LLM API calls with input/output messages
- `$ai_span`: Logical spans with state transitions
- `$ai_embedding`: Embedding generation events (text input → vector)
- `$ai_trace`: Full traces with hierarchical structure

**Options:**
- `max_length`: Maximum character count (default: 2000000)
- `truncated`: Enable middle-content truncation within events (default: true)
- `truncate_buffer`: Characters at start/end when truncating (default: 1000)
- `include_markers`: Use interactive markers vs plain text indicators (default: true)
  - Frontend: set true for `<<<TRUNCATED|base64|...>>>` markers
  - Backend/LLM: set false for `... (X chars truncated) ...` text
- `collapsed`: Show summary vs full trace tree (default: false)
- `include_hierarchy`: Include tree structure for traces (default: true)
- `max_depth`: Maximum depth for hierarchical rendering (default: unlimited)
- `tools_collapse_threshold`: Number of tools before auto-collapsing list (default: 5)
  - Tool lists >5 items show `<<<TOOLS_EXPANDABLE|...>>>` marker for frontend
  - Or `[+] AVAILABLE TOOLS: N` for backend when `include_markers: false`
- `include_line_numbers`: Prefix each line with line number like L001:, L010: (default: false)

**Use Cases:**
- Frontend display: `truncated: true, include_markers: true, include_line_numbers: true`
- Backend LLM context (summary): `truncated: true, include_markers: false, collapsed: true`
- Backend LLM context (full): `truncated: false`

The response includes the formatted text and metadata about the rendering.
        
 */
export const LlmAnalyticsTextReprCreateBody = /* @__PURE__ */ zod.object({
    event_type: zod
        .enum(['$ai_generation', '$ai_span', '$ai_embedding', '$ai_trace'])
        .describe(
            '* `$ai_generation` - $ai_generation\n* `$ai_span` - $ai_span\n* `$ai_embedding` - $ai_embedding\n* `$ai_trace` - $ai_trace'
        )
        .describe(
            'Type of LLM event to stringify\n\n* `$ai_generation` - $ai_generation\n* `$ai_span` - $ai_span\n* `$ai_embedding` - $ai_embedding\n* `$ai_trace` - $ai_trace'
        ),
    data: zod.unknown().describe("Event data to stringify. For traces, should include 'trace' and 'hierarchy' fields."),
    options: zod
        .object({
            max_length: zod.number().optional().describe('Maximum length of generated text (default: 2000000)'),
            truncated: zod
                .boolean()
                .optional()
                .describe('Use truncation for long content within events (default: true)'),
            truncate_buffer: zod
                .number()
                .optional()
                .describe('Characters to show at start/end when truncating (default: 1000)'),
            include_markers: zod
                .boolean()
                .optional()
                .describe('Use interactive markers for frontend vs plain text for backend/LLM (default: true)'),
            collapsed: zod
                .boolean()
                .optional()
                .describe('Show summary vs full tree hierarchy for traces (default: false)'),
            include_metadata: zod.boolean().optional().describe('Include metadata in response'),
            include_hierarchy: zod.boolean().optional().describe('Include hierarchy information (for traces)'),
            max_depth: zod.number().optional().describe('Maximum depth for hierarchical rendering'),
            tools_collapse_threshold: zod
                .number()
                .optional()
                .describe('Number of tools before collapsing the list (default: 5)'),
            include_line_numbers: zod
                .boolean()
                .optional()
                .describe('Prefix each line with line number (default: false)'),
        })
        .optional()
        .describe('Optional configuration for text generation'),
})

export const llmAnalyticsTraceReviewsCreateBodyTraceIdMax = 255

export const llmAnalyticsTraceReviewsCreateBodyScoresItemCategoricalValuesItemMax = 128

export const llmAnalyticsTraceReviewsCreateBodyScoresItemNumericValueRegExp = new RegExp('^-?\\d{0,6}(?:\\.\\d{0,6})?$')

export const LlmAnalyticsTraceReviewsCreateBody = /* @__PURE__ */ zod.object({
    trace_id: zod
        .string()
        .max(llmAnalyticsTraceReviewsCreateBodyTraceIdMax)
        .describe('Trace ID for the review. Only one active review can exist per trace and team.'),
    comment: zod.string().nullish().describe('Optional human comment or reasoning for the review.'),
    scores: zod
        .array(
            zod.object({
                definition_id: zod.uuid().describe('Stable scorer definition ID.'),
                definition_version_id: zod
                    .uuid()
                    .nullish()
                    .describe("Optional immutable scorer version ID. Defaults to the scorer's current version."),
                categorical_values: zod
                    .array(zod.string().max(llmAnalyticsTraceReviewsCreateBodyScoresItemCategoricalValuesItemMax))
                    .min(1)
                    .nullish()
                    .describe('Categorical option keys selected for this score.'),
                numeric_value: zod
                    .string()
                    .regex(llmAnalyticsTraceReviewsCreateBodyScoresItemNumericValueRegExp)
                    .nullish()
                    .describe('Numeric value selected for this score.'),
                boolean_value: zod.boolean().nullish().describe('Boolean value selected for this score.'),
            })
        )
        .optional()
        .describe('Full desired score set for this review. Omit scorers you want to leave blank.'),
    queue_id: zod
        .uuid()
        .nullish()
        .describe(
            'Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.'
        ),
})

export const llmAnalyticsTraceReviewsPartialUpdateBodyTraceIdMax = 255

export const llmAnalyticsTraceReviewsPartialUpdateBodyScoresItemCategoricalValuesItemMax = 128

export const llmAnalyticsTraceReviewsPartialUpdateBodyScoresItemNumericValueRegExp = new RegExp(
    '^-?\\d{0,6}(?:\\.\\d{0,6})?$'
)

export const LlmAnalyticsTraceReviewsPartialUpdateBody = /* @__PURE__ */ zod.object({
    trace_id: zod
        .string()
        .max(llmAnalyticsTraceReviewsPartialUpdateBodyTraceIdMax)
        .optional()
        .describe('Trace ID for the review. Only one active review can exist per trace and team.'),
    comment: zod.string().nullish().describe('Optional human comment or reasoning for the review.'),
    scores: zod
        .array(
            zod.object({
                definition_id: zod.uuid().describe('Stable scorer definition ID.'),
                definition_version_id: zod
                    .uuid()
                    .nullish()
                    .describe("Optional immutable scorer version ID. Defaults to the scorer's current version."),
                categorical_values: zod
                    .array(
                        zod.string().max(llmAnalyticsTraceReviewsPartialUpdateBodyScoresItemCategoricalValuesItemMax)
                    )
                    .min(1)
                    .nullish()
                    .describe('Categorical option keys selected for this score.'),
                numeric_value: zod
                    .string()
                    .regex(llmAnalyticsTraceReviewsPartialUpdateBodyScoresItemNumericValueRegExp)
                    .nullish()
                    .describe('Numeric value selected for this score.'),
                boolean_value: zod.boolean().nullish().describe('Boolean value selected for this score.'),
            })
        )
        .optional()
        .describe('Full desired score set for this review. Omit scorers you want to leave blank.'),
    queue_id: zod
        .uuid()
        .nullish()
        .describe(
            'Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.'
        ),
})

/**
 * Translate text to target language.
 */
export const llmAnalyticsTranslateCreateBodyTextMax = 10000

export const llmAnalyticsTranslateCreateBodyTargetLanguageDefault = `en`
export const llmAnalyticsTranslateCreateBodyTargetLanguageMax = 10

export const LlmAnalyticsTranslateCreateBody = /* @__PURE__ */ zod.object({
    text: zod.string().max(llmAnalyticsTranslateCreateBodyTextMax).describe('The text to translate'),
    target_language: zod
        .string()
        .max(llmAnalyticsTranslateCreateBodyTargetLanguageMax)
        .default(llmAnalyticsTranslateCreateBodyTargetLanguageDefault)
        .describe("Target language code (default: 'en' for English)"),
})

export const llmPromptsCreateBodyNameMax = 255

export const LlmPromptsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(llmPromptsCreateBodyNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
})

export const LlmPromptsNamePartialUpdateBody = /* @__PURE__ */ zod.object({
    prompt: zod
        .unknown()
        .optional()
        .describe('Full prompt payload to publish as a new version. Mutually exclusive with edits.'),
    edits: zod
        .array(
            zod.object({
                old: zod.string().describe('Text to find in the current prompt. Must match exactly once.'),
                new: zod.string().describe('Replacement text.'),
            })
        )
        .optional()
        .describe(
            "List of find/replace operations to apply to the current prompt version. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with prompt."
        ),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Latest version you are editing from. Used for optimistic concurrency checks.'),
})

export const llmPromptsNameArchiveCreateBodyNameMax = 255

export const LlmPromptsNameArchiveCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(llmPromptsNameArchiveCreateBodyNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
})

export const llmPromptsNameDuplicateCreateBodyNewNameMax = 255

export const LlmPromptsNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    new_name: zod
        .string()
        .max(llmPromptsNameDuplicateCreateBodyNewNameMax)
        .describe(
            'Name for the duplicated prompt. Must be unique and use only letters, numbers, hyphens, and underscores.'
        ),
})

export const llmSkillsCreateBodyNameMax = 64

export const llmSkillsCreateBodyDescriptionMax = 4096

export const llmSkillsCreateBodyLicenseMax = 255

export const llmSkillsCreateBodyCompatibilityMax = 500

export const llmSkillsCreateBodyFilesItemPathMax = 500

export const llmSkillsCreateBodyFilesItemContentTypeDefault = `text/plain`
export const llmSkillsCreateBodyFilesItemContentTypeMax = 100

export const LlmSkillsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .max(llmSkillsCreateBodyNameMax)
            .describe('Unique skill name. Lowercase letters, numbers, and hyphens only. Max 64 characters.'),
        description: zod
            .string()
            .max(llmSkillsCreateBodyDescriptionMax)
            .describe('What this skill does and when to use it. Max 4096 characters.'),
        body: zod.string().describe('The SKILL.md instruction content (markdown).'),
        license: zod
            .string()
            .max(llmSkillsCreateBodyLicenseMax)
            .optional()
            .describe('License name or reference to a bundled license file.'),
        compatibility: zod
            .string()
            .max(llmSkillsCreateBodyCompatibilityMax)
            .optional()
            .describe('Environment requirements (intended product, system packages, network access, etc.).'),
        allowed_tools: zod.array(zod.string()).optional().describe('List of pre-approved tools the skill may use.'),
        metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
        files: zod
            .array(
                zod.object({
                    path: zod
                        .string()
                        .max(llmSkillsCreateBodyFilesItemPathMax)
                        .describe(
                            "File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'."
                        ),
                    content: zod.string().describe('Text content of the file.'),
                    content_type: zod
                        .string()
                        .max(llmSkillsCreateBodyFilesItemContentTypeMax)
                        .default(llmSkillsCreateBodyFilesItemContentTypeDefault)
                        .describe('MIME type of the file content.'),
                })
            )
            .optional()
            .describe('Bundled files to include with the initial version (scripts, references, assets).'),
    })
    .describe('Create serializer — accepts bundled files as write-only input on POST.')

export const llmSkillsNamePartialUpdateBodyDescriptionMax = 4096

export const llmSkillsNamePartialUpdateBodyLicenseMax = 255

export const llmSkillsNamePartialUpdateBodyCompatibilityMax = 500

export const llmSkillsNamePartialUpdateBodyFilesItemPathMax = 500

export const llmSkillsNamePartialUpdateBodyFilesItemContentTypeDefault = `text/plain`
export const llmSkillsNamePartialUpdateBodyFilesItemContentTypeMax = 100

export const llmSkillsNamePartialUpdateBodyFileEditsItemPathMax = 500

export const LlmSkillsNamePartialUpdateBody = /* @__PURE__ */ zod.object({
    body: zod
        .string()
        .optional()
        .describe(
            'Full skill body (SKILL.md instruction content) to publish as a new version. Mutually exclusive with edits.'
        ),
    edits: zod
        .array(
            zod.object({
                old: zod.string().describe('Text to find in the target content. Must match exactly once.'),
                new: zod.string().describe('Replacement text.'),
            })
        )
        .optional()
        .describe(
            "List of find/replace operations to apply to the current skill body. Each edit's 'old' text must match exactly once. Edits are applied sequentially. Mutually exclusive with body."
        ),
    description: zod
        .string()
        .max(llmSkillsNamePartialUpdateBodyDescriptionMax)
        .optional()
        .describe('Updated description for the new version.'),
    license: zod
        .string()
        .max(llmSkillsNamePartialUpdateBodyLicenseMax)
        .optional()
        .describe('License name or reference.'),
    compatibility: zod
        .string()
        .max(llmSkillsNamePartialUpdateBodyCompatibilityMax)
        .optional()
        .describe('Environment requirements.'),
    allowed_tools: zod.array(zod.string()).optional().describe('List of pre-approved tools the skill may use.'),
    metadata: zod.record(zod.string(), zod.unknown()).optional().describe('Arbitrary key-value metadata.'),
    files: zod
        .array(
            zod.object({
                path: zod
                    .string()
                    .max(llmSkillsNamePartialUpdateBodyFilesItemPathMax)
                    .describe("File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'."),
                content: zod.string().describe('Text content of the file.'),
                content_type: zod
                    .string()
                    .max(llmSkillsNamePartialUpdateBodyFilesItemContentTypeMax)
                    .default(llmSkillsNamePartialUpdateBodyFilesItemContentTypeDefault)
                    .describe('MIME type of the file content.'),
            })
        )
        .optional()
        .describe(
            'Bundled files to include with this version. Replaces all files from the previous version. Mutually exclusive with file_edits.'
        ),
    file_edits: zod
        .array(
            zod.object({
                path: zod
                    .string()
                    .max(llmSkillsNamePartialUpdateBodyFileEditsItemPathMax)
                    .describe(
                        'Path of the bundled file to edit. Must match an existing file on the current skill version.'
                    ),
                edits: zod
                    .array(
                        zod.object({
                            old: zod.string().describe('Text to find in the target content. Must match exactly once.'),
                            new: zod.string().describe('Replacement text.'),
                        })
                    )
                    .describe("Sequential find/replace operations to apply to this file's content."),
            })
        )
        .optional()
        .describe(
            "Per-file find/replace updates. Each entry targets one existing file by path and applies sequential edits to its content. Non-targeted files carry forward unchanged. Cannot add, remove, or rename files — use 'files' for that. Mutually exclusive with files."
        ),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe('Latest version you are editing from. Used for optimistic concurrency checks.'),
})

export const llmSkillsNameDuplicateCreateBodyNewNameMax = 64

export const LlmSkillsNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    new_name: zod
        .string()
        .max(llmSkillsNameDuplicateCreateBodyNewNameMax)
        .describe('Name for the duplicated skill. Must be unique.'),
})

export const llmSkillsNameFilesCreateBodyPathMax = 500

export const llmSkillsNameFilesCreateBodyContentTypeDefault = `text/plain`
export const llmSkillsNameFilesCreateBodyContentTypeMax = 100

export const LlmSkillsNameFilesCreateBody = /* @__PURE__ */ zod.object({
    path: zod
        .string()
        .max(llmSkillsNameFilesCreateBodyPathMax)
        .describe("File path relative to skill root, e.g. 'scripts/setup.sh' or 'references/guide.md'."),
    content: zod.string().describe('Text content of the file.'),
    content_type: zod
        .string()
        .max(llmSkillsNameFilesCreateBodyContentTypeMax)
        .default(llmSkillsNameFilesCreateBodyContentTypeDefault)
        .describe('MIME type of the file content.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.'
        ),
})

export const llmSkillsNameFilesRenameCreateBodyOldPathMax = 500

export const llmSkillsNameFilesRenameCreateBodyNewPathMax = 500

export const LlmSkillsNameFilesRenameCreateBody = /* @__PURE__ */ zod.object({
    old_path: zod.string().max(llmSkillsNameFilesRenameCreateBodyOldPathMax).describe('Current file path to rename.'),
    new_path: zod
        .string()
        .max(llmSkillsNameFilesRenameCreateBodyNewPathMax)
        .describe('New file path. Must not already exist in the skill.'),
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.'
        ),
})

export const datasetItemsCreateBodyRefTraceIdMax = 255

export const datasetItemsCreateBodyRefSourceIdMax = 255

export const DatasetItemsCreateBody = /* @__PURE__ */ zod.object({
    dataset: zod.uuid(),
    input: zod.unknown().nullish(),
    output: zod.unknown().nullish(),
    metadata: zod.unknown().nullish(),
    ref_trace_id: zod.string().max(datasetItemsCreateBodyRefTraceIdMax).nullish(),
    ref_timestamp: zod.iso.datetime({}).nullish(),
    ref_source_id: zod.string().max(datasetItemsCreateBodyRefSourceIdMax).nullish(),
    deleted: zod.boolean().nullish(),
})

export const datasetItemsUpdateBodyRefTraceIdMax = 255

export const datasetItemsUpdateBodyRefSourceIdMax = 255

export const DatasetItemsUpdateBody = /* @__PURE__ */ zod.object({
    dataset: zod.uuid(),
    input: zod.unknown().nullish(),
    output: zod.unknown().nullish(),
    metadata: zod.unknown().nullish(),
    ref_trace_id: zod.string().max(datasetItemsUpdateBodyRefTraceIdMax).nullish(),
    ref_timestamp: zod.iso.datetime({}).nullish(),
    ref_source_id: zod.string().max(datasetItemsUpdateBodyRefSourceIdMax).nullish(),
    deleted: zod.boolean().nullish(),
})

export const datasetItemsPartialUpdateBodyRefTraceIdMax = 255

export const datasetItemsPartialUpdateBodyRefSourceIdMax = 255

export const DatasetItemsPartialUpdateBody = /* @__PURE__ */ zod.object({
    dataset: zod.uuid().optional(),
    input: zod.unknown().nullish(),
    output: zod.unknown().nullish(),
    metadata: zod.unknown().nullish(),
    ref_trace_id: zod.string().max(datasetItemsPartialUpdateBodyRefTraceIdMax).nullish(),
    ref_timestamp: zod.iso.datetime({}).nullish(),
    ref_source_id: zod.string().max(datasetItemsPartialUpdateBodyRefSourceIdMax).nullish(),
    deleted: zod.boolean().nullish(),
})

export const datasetsCreateBodyNameMax = 400

export const DatasetsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(datasetsCreateBodyNameMax),
    description: zod.string().nullish(),
    metadata: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
})

export const datasetsUpdateBodyNameMax = 400

export const DatasetsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(datasetsUpdateBodyNameMax),
    description: zod.string().nullish(),
    metadata: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
})

export const datasetsPartialUpdateBodyNameMax = 400

export const DatasetsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(datasetsPartialUpdateBodyNameMax).optional(),
    description: zod.string().nullish(),
    metadata: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
})
