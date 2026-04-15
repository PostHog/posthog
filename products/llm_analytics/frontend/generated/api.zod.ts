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

export const evaluationsListResponseResultsItemNameMax = 400

export const evaluationsListResponseResultsItemModelConfigurationOneModelMax = 100

export const evaluationsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const evaluationsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const evaluationsListResponseResultsItemCreatedByOneLastNameMax = 150

export const evaluationsListResponseResultsItemCreatedByOneEmailMax = 254

export const EvaluationsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().max(evaluationsListResponseResultsItemNameMax),
            description: zod.string().optional(),
            enabled: zod.boolean().optional(),
            evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
            evaluation_config: zod.unknown().optional(),
            output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
            output_config: zod.unknown().optional(),
            conditions: zod.unknown().optional(),
            model_configuration: zod
                .object({
                    provider: zod
                        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                        .describe(
                            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                        ),
                    model: zod.string().max(evaluationsListResponseResultsItemModelConfigurationOneModelMax),
                    provider_key_id: zod.uuid().nullish(),
                    provider_key_name: zod.string().nullable(),
                })
                .describe('Nested serializer for model configuration.')
                .nullish(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(evaluationsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(evaluationsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(evaluationsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(evaluationsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            deleted: zod.boolean().optional(),
        })
    ),
})

export const evaluationsCreateBodyNameMax = 400

export const evaluationsCreateBodyModelConfigurationOneModelMax = 100

export const EvaluationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(evaluationsCreateBodyNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
    evaluation_config: zod.unknown().optional(),
    output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
    output_config: zod.unknown().optional(),
    conditions: zod.unknown().optional(),
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
    deleted: zod.boolean().optional(),
})

/**
 * Test Hog evaluation code against sample events without saving.
 */
export const evaluationsTestHogCreateBodyNameMax = 400

export const evaluationsTestHogCreateBodyModelConfigurationOneModelMax = 100

export const EvaluationsTestHogCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(evaluationsTestHogCreateBodyNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
    evaluation_config: zod.unknown().optional(),
    output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
    output_config: zod.unknown().optional(),
    conditions: zod.unknown().optional(),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsTestHogCreateBodyModelConfigurationOneModelMax),
            provider_key_id: zod.uuid().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    deleted: zod.boolean().optional(),
})

export const evaluationsTestHogCreateResponseNameMax = 400

export const evaluationsTestHogCreateResponseModelConfigurationOneModelMax = 100

export const evaluationsTestHogCreateResponseCreatedByOneDistinctIdMax = 200

export const evaluationsTestHogCreateResponseCreatedByOneFirstNameMax = 150

export const evaluationsTestHogCreateResponseCreatedByOneLastNameMax = 150

export const evaluationsTestHogCreateResponseCreatedByOneEmailMax = 254

export const EvaluationsTestHogCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(evaluationsTestHogCreateResponseNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    evaluation_type: zod.enum(['llm_judge', 'hog']).describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog'),
    evaluation_config: zod.unknown().optional(),
    output_type: zod.enum(['boolean']).describe('* `boolean` - Boolean (Pass/Fail)'),
    output_config: zod.unknown().optional(),
    conditions: zod.unknown().optional(),
    model_configuration: zod
        .object({
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            model: zod.string().max(evaluationsTestHogCreateResponseModelConfigurationOneModelMax),
            provider_key_id: zod.uuid().nullish(),
            provider_key_name: zod.string().nullable(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(evaluationsTestHogCreateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(evaluationsTestHogCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(evaluationsTestHogCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(evaluationsTestHogCreateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    deleted: zod.boolean().optional(),
})

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const llmAnalyticsClusteringJobsListResponseResultsItemNameMax = 100

export const LlmAnalyticsClusteringJobsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().max(llmAnalyticsClusteringJobsListResponseResultsItemNameMax),
            analysis_level: zod
                .enum(['trace', 'generation'])
                .describe('* `trace` - trace\n* `generation` - generation'),
            event_filters: zod.unknown().optional(),
            enabled: zod.boolean().optional(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
        })
    ),
})

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const llmAnalyticsClusteringJobsCreateBodyNameMax = 100

export const LlmAnalyticsClusteringJobsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsClusteringJobsCreateBodyNameMax),
    analysis_level: zod.enum(['trace', 'generation']).describe('* `trace` - trace\n* `generation` - generation'),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
})

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const llmAnalyticsClusteringJobsRetrieveResponseNameMax = 100

export const LlmAnalyticsClusteringJobsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(llmAnalyticsClusteringJobsRetrieveResponseNameMax),
    analysis_level: zod.enum(['trace', 'generation']).describe('* `trace` - trace\n* `generation` - generation'),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const llmAnalyticsClusteringJobsUpdateBodyNameMax = 100

export const LlmAnalyticsClusteringJobsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsClusteringJobsUpdateBodyNameMax),
    analysis_level: zod.enum(['trace', 'generation']).describe('* `trace` - trace\n* `generation` - generation'),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
})

export const llmAnalyticsClusteringJobsUpdateResponseNameMax = 100

export const LlmAnalyticsClusteringJobsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(llmAnalyticsClusteringJobsUpdateResponseNameMax),
    analysis_level: zod.enum(['trace', 'generation']).describe('* `trace` - trace\n* `generation` - generation'),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
})

/**
 * CRUD for clustering job configurations (max 5 per team).
 */
export const llmAnalyticsClusteringJobsPartialUpdateBodyNameMax = 100

export const LlmAnalyticsClusteringJobsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsClusteringJobsPartialUpdateBodyNameMax).optional(),
    analysis_level: zod
        .enum(['trace', 'generation'])
        .optional()
        .describe('* `trace` - trace\n* `generation` - generation'),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
})

export const llmAnalyticsClusteringJobsPartialUpdateResponseNameMax = 100

export const LlmAnalyticsClusteringJobsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(llmAnalyticsClusteringJobsPartialUpdateResponseNameMax),
    analysis_level: zod.enum(['trace', 'generation']).describe('* `trace` - trace\n* `generation` - generation'),
    event_filters: zod.unknown().optional(),
    enabled: zod.boolean().optional(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
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

export const LlmAnalyticsEvaluationSummaryCreateResponse = /* @__PURE__ */ zod.object({
    overall_assessment: zod.string(),
    pass_patterns: zod.array(
        zod.object({
            title: zod.string(),
            description: zod.string(),
            frequency: zod.string(),
            example_generation_ids: zod.array(zod.string()),
        })
    ),
    fail_patterns: zod.array(
        zod.object({
            title: zod.string(),
            description: zod.string(),
            frequency: zod.string(),
            example_generation_ids: zod.array(zod.string()),
        })
    ),
    na_patterns: zod.array(
        zod.object({
            title: zod.string(),
            description: zod.string(),
            frequency: zod.string(),
            example_generation_ids: zod.array(zod.string()),
        })
    ),
    recommendations: zod.array(zod.string()),
    statistics: zod.object({
        total_analyzed: zod.number(),
        pass_count: zod.number(),
        fail_count: zod.number(),
        na_count: zod.number(),
    }),
})

export const llmAnalyticsProviderKeysListResponseResultsItemNameMax = 255

export const llmAnalyticsProviderKeysListResponseResultsItemSetAsActiveDefault = false
export const llmAnalyticsProviderKeysListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const llmAnalyticsProviderKeysListResponseResultsItemCreatedByOneFirstNameMax = 150

export const llmAnalyticsProviderKeysListResponseResultsItemCreatedByOneLastNameMax = 150

export const llmAnalyticsProviderKeysListResponseResultsItemCreatedByOneEmailMax = 254

export const LlmAnalyticsProviderKeysListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            provider: zod
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
                ),
            name: zod.string().max(llmAnalyticsProviderKeysListResponseResultsItemNameMax),
            state: zod
                .enum(['unknown', 'ok', 'invalid', 'error'])
                .describe('* `unknown` - Unknown\n* `ok` - Ok\n* `invalid` - Invalid\n* `error` - Error'),
            error_message: zod.string().nullable(),
            api_key: zod.string().optional(),
            api_key_masked: zod.string(),
            set_as_active: zod.boolean().default(llmAnalyticsProviderKeysListResponseResultsItemSetAsActiveDefault),
            created_at: zod.iso.datetime({}),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(llmAnalyticsProviderKeysListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(llmAnalyticsProviderKeysListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(llmAnalyticsProviderKeysListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(llmAnalyticsProviderKeysListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            last_used_at: zod.iso.datetime({}).nullable(),
        })
    ),
})

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

export const llmAnalyticsProviderKeysRetrieveResponseNameMax = 255

export const llmAnalyticsProviderKeysRetrieveResponseSetAsActiveDefault = false
export const llmAnalyticsProviderKeysRetrieveResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsProviderKeysRetrieveResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsProviderKeysRetrieveResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsProviderKeysRetrieveResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsProviderKeysRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysRetrieveResponseNameMax),
    state: zod
        .enum(['unknown', 'ok', 'invalid', 'error'])
        .describe('* `unknown` - Unknown\n* `ok` - Ok\n* `invalid` - Invalid\n* `error` - Error'),
    error_message: zod.string().nullable(),
    api_key: zod.string().optional(),
    api_key_masked: zod.string(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysRetrieveResponseSetAsActiveDefault),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(llmAnalyticsProviderKeysRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(llmAnalyticsProviderKeysRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(llmAnalyticsProviderKeysRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(llmAnalyticsProviderKeysRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_used_at: zod.iso.datetime({}).nullable(),
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

export const llmAnalyticsProviderKeysUpdateResponseNameMax = 255

export const llmAnalyticsProviderKeysUpdateResponseSetAsActiveDefault = false
export const llmAnalyticsProviderKeysUpdateResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsProviderKeysUpdateResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsProviderKeysUpdateResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsProviderKeysUpdateResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsProviderKeysUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysUpdateResponseNameMax),
    state: zod
        .enum(['unknown', 'ok', 'invalid', 'error'])
        .describe('* `unknown` - Unknown\n* `ok` - Ok\n* `invalid` - Invalid\n* `error` - Error'),
    error_message: zod.string().nullable(),
    api_key: zod.string().optional(),
    api_key_masked: zod.string(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysUpdateResponseSetAsActiveDefault),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(llmAnalyticsProviderKeysUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(llmAnalyticsProviderKeysUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(llmAnalyticsProviderKeysUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(llmAnalyticsProviderKeysUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_used_at: zod.iso.datetime({}).nullable(),
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

export const llmAnalyticsProviderKeysPartialUpdateResponseNameMax = 255

export const llmAnalyticsProviderKeysPartialUpdateResponseSetAsActiveDefault = false
export const llmAnalyticsProviderKeysPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsProviderKeysPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsProviderKeysPartialUpdateResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsProviderKeysPartialUpdateResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsProviderKeysPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysPartialUpdateResponseNameMax),
    state: zod
        .enum(['unknown', 'ok', 'invalid', 'error'])
        .describe('* `unknown` - Unknown\n* `ok` - Ok\n* `invalid` - Invalid\n* `error` - Error'),
    error_message: zod.string().nullable(),
    api_key: zod.string().optional(),
    api_key_masked: zod.string(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysPartialUpdateResponseSetAsActiveDefault),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(llmAnalyticsProviderKeysPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(llmAnalyticsProviderKeysPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(llmAnalyticsProviderKeysPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(llmAnalyticsProviderKeysPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_used_at: zod.iso.datetime({}).nullable(),
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

export const llmAnalyticsProviderKeysAssignCreateResponseNameMax = 255

export const llmAnalyticsProviderKeysAssignCreateResponseSetAsActiveDefault = false
export const llmAnalyticsProviderKeysAssignCreateResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsProviderKeysAssignCreateResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsProviderKeysAssignCreateResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsProviderKeysAssignCreateResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsProviderKeysAssignCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysAssignCreateResponseNameMax),
    state: zod
        .enum(['unknown', 'ok', 'invalid', 'error'])
        .describe('* `unknown` - Unknown\n* `ok` - Ok\n* `invalid` - Invalid\n* `error` - Error'),
    error_message: zod.string().nullable(),
    api_key: zod.string().optional(),
    api_key_masked: zod.string(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysAssignCreateResponseSetAsActiveDefault),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(llmAnalyticsProviderKeysAssignCreateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(llmAnalyticsProviderKeysAssignCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(llmAnalyticsProviderKeysAssignCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(llmAnalyticsProviderKeysAssignCreateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_used_at: zod.iso.datetime({}).nullable(),
})

/**
 * Get evaluations using this key and alternative keys for replacement.
 */
export const llmAnalyticsProviderKeysDependentConfigsRetrieveResponseNameMax = 255

export const llmAnalyticsProviderKeysDependentConfigsRetrieveResponseSetAsActiveDefault = false
export const llmAnalyticsProviderKeysDependentConfigsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsProviderKeysDependentConfigsRetrieveResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsProviderKeysDependentConfigsRetrieveResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsProviderKeysDependentConfigsRetrieveResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsProviderKeysDependentConfigsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysDependentConfigsRetrieveResponseNameMax),
    state: zod
        .enum(['unknown', 'ok', 'invalid', 'error'])
        .describe('* `unknown` - Unknown\n* `ok` - Ok\n* `invalid` - Invalid\n* `error` - Error'),
    error_message: zod.string().nullable(),
    api_key: zod.string().optional(),
    api_key_masked: zod.string(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysDependentConfigsRetrieveResponseSetAsActiveDefault),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod
            .string()
            .max(llmAnalyticsProviderKeysDependentConfigsRetrieveResponseCreatedByOneDistinctIdMax)
            .nullish(),
        first_name: zod
            .string()
            .max(llmAnalyticsProviderKeysDependentConfigsRetrieveResponseCreatedByOneFirstNameMax)
            .optional(),
        last_name: zod
            .string()
            .max(llmAnalyticsProviderKeysDependentConfigsRetrieveResponseCreatedByOneLastNameMax)
            .optional(),
        email: zod.email().max(llmAnalyticsProviderKeysDependentConfigsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_used_at: zod.iso.datetime({}).nullable(),
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

export const llmAnalyticsProviderKeysValidateCreateResponseNameMax = 255

export const llmAnalyticsProviderKeysValidateCreateResponseSetAsActiveDefault = false
export const llmAnalyticsProviderKeysValidateCreateResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsProviderKeysValidateCreateResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsProviderKeysValidateCreateResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsProviderKeysValidateCreateResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsProviderKeysValidateCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysValidateCreateResponseNameMax),
    state: zod
        .enum(['unknown', 'ok', 'invalid', 'error'])
        .describe('* `unknown` - Unknown\n* `ok` - Ok\n* `invalid` - Invalid\n* `error` - Error'),
    error_message: zod.string().nullable(),
    api_key: zod.string().optional(),
    api_key_masked: zod.string(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysValidateCreateResponseSetAsActiveDefault),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod
            .string()
            .max(llmAnalyticsProviderKeysValidateCreateResponseCreatedByOneDistinctIdMax)
            .nullish(),
        first_name: zod.string().max(llmAnalyticsProviderKeysValidateCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(llmAnalyticsProviderKeysValidateCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(llmAnalyticsProviderKeysValidateCreateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_used_at: zod.iso.datetime({}).nullable(),
})

/**
 * List enabled evaluations currently using trial credits for a given provider.
 */
export const llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseNameMax = 255

export const llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseSetAsActiveDefault = false
export const llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsProviderKeysTrialEvaluationsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    provider: zod
        .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks'])
        .describe(
            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks'
        ),
    name: zod.string().max(llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseNameMax),
    state: zod
        .enum(['unknown', 'ok', 'invalid', 'error'])
        .describe('* `unknown` - Unknown\n* `ok` - Ok\n* `invalid` - Invalid\n* `error` - Error'),
    error_message: zod.string().nullable(),
    api_key: zod.string().optional(),
    api_key_masked: zod.string(),
    set_as_active: zod.boolean().default(llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseSetAsActiveDefault),
    created_at: zod.iso.datetime({}),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod
            .string()
            .max(llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseCreatedByOneDistinctIdMax)
            .nullish(),
        first_name: zod
            .string()
            .max(llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseCreatedByOneFirstNameMax)
            .optional(),
        last_name: zod
            .string()
            .max(llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseCreatedByOneLastNameMax)
            .optional(),
        email: zod.email().max(llmAnalyticsProviderKeysTrialEvaluationsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    last_used_at: zod.iso.datetime({}).nullable(),
})

export const llmAnalyticsReviewQueueItemsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const llmAnalyticsReviewQueueItemsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const llmAnalyticsReviewQueueItemsListResponseResultsItemCreatedByOneLastNameMax = 150

export const llmAnalyticsReviewQueueItemsListResponseResultsItemCreatedByOneEmailMax = 254

export const LlmAnalyticsReviewQueueItemsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            queue_id: zod.uuid().describe('Review queue ID that currently owns this pending trace.'),
            queue_name: zod
                .string()
                .describe('Human-readable name of the queue that currently owns this pending trace.'),
            trace_id: zod.string().describe('Trace ID currently pending human review.'),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
            created_by: zod
                .object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(llmAnalyticsReviewQueueItemsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(llmAnalyticsReviewQueueItemsListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(llmAnalyticsReviewQueueItemsListResponseResultsItemCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(llmAnalyticsReviewQueueItemsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
                .describe('User who queued this trace.'),
            team: zod.number(),
        })
    ),
})

export const llmAnalyticsReviewQueueItemsCreateBodyTraceIdMax = 255

export const LlmAnalyticsReviewQueueItemsCreateBody = /* @__PURE__ */ zod.object({
    queue_id: zod.uuid().describe('Review queue ID that should own this pending trace.'),
    trace_id: zod
        .string()
        .max(llmAnalyticsReviewQueueItemsCreateBodyTraceIdMax)
        .describe('Trace ID to add to the selected review queue.'),
})

export const llmAnalyticsReviewQueueItemsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsReviewQueueItemsRetrieveResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsReviewQueueItemsRetrieveResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsReviewQueueItemsRetrieveResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsReviewQueueItemsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    queue_id: zod.uuid().describe('Review queue ID that currently owns this pending trace.'),
    queue_name: zod.string().describe('Human-readable name of the queue that currently owns this pending trace.'),
    trace_id: zod.string().describe('Trace ID currently pending human review.'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    created_by: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(llmAnalyticsReviewQueueItemsRetrieveResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(llmAnalyticsReviewQueueItemsRetrieveResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod.string().max(llmAnalyticsReviewQueueItemsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(llmAnalyticsReviewQueueItemsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .describe('User who queued this trace.'),
    team: zod.number(),
})

export const LlmAnalyticsReviewQueueItemsPartialUpdateBody = /* @__PURE__ */ zod.object({
    queue_id: zod.uuid().optional().describe('Review queue ID that should own this pending trace.'),
})

export const llmAnalyticsReviewQueueItemsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsReviewQueueItemsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsReviewQueueItemsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsReviewQueueItemsPartialUpdateResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsReviewQueueItemsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    queue_id: zod.uuid().describe('Review queue ID that currently owns this pending trace.'),
    queue_name: zod.string().describe('Human-readable name of the queue that currently owns this pending trace.'),
    trace_id: zod.string().describe('Trace ID currently pending human review.'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    created_by: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(llmAnalyticsReviewQueueItemsPartialUpdateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(llmAnalyticsReviewQueueItemsPartialUpdateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(llmAnalyticsReviewQueueItemsPartialUpdateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(llmAnalyticsReviewQueueItemsPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .describe('User who queued this trace.'),
    team: zod.number(),
})

export const llmAnalyticsReviewQueuesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const llmAnalyticsReviewQueuesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const llmAnalyticsReviewQueuesListResponseResultsItemCreatedByOneLastNameMax = 150

export const llmAnalyticsReviewQueuesListResponseResultsItemCreatedByOneEmailMax = 254

export const LlmAnalyticsReviewQueuesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().describe('Human-readable queue name.'),
            pending_item_count: zod.number().describe('Number of pending traces currently assigned to this queue.'),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
            created_by: zod
                .object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(llmAnalyticsReviewQueuesListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(llmAnalyticsReviewQueuesListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(llmAnalyticsReviewQueuesListResponseResultsItemCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(llmAnalyticsReviewQueuesListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
                .describe('User who created this review queue.'),
            team: zod.number(),
        })
    ),
})

export const llmAnalyticsReviewQueuesCreateBodyNameMax = 255

export const LlmAnalyticsReviewQueuesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsReviewQueuesCreateBodyNameMax).describe('Human-readable queue name.'),
})

export const llmAnalyticsReviewQueuesRetrieveResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsReviewQueuesRetrieveResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsReviewQueuesRetrieveResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsReviewQueuesRetrieveResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsReviewQueuesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().describe('Human-readable queue name.'),
    pending_item_count: zod.number().describe('Number of pending traces currently assigned to this queue.'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    created_by: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(llmAnalyticsReviewQueuesRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(llmAnalyticsReviewQueuesRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(llmAnalyticsReviewQueuesRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(llmAnalyticsReviewQueuesRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .describe('User who created this review queue.'),
    team: zod.number(),
})

export const llmAnalyticsReviewQueuesPartialUpdateBodyNameMax = 255

export const LlmAnalyticsReviewQueuesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(llmAnalyticsReviewQueuesPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable queue name.'),
})

export const llmAnalyticsReviewQueuesPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsReviewQueuesPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsReviewQueuesPartialUpdateResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsReviewQueuesPartialUpdateResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsReviewQueuesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().describe('Human-readable queue name.'),
    pending_item_count: zod.number().describe('Number of pending traces currently assigned to this queue.'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    created_by: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(llmAnalyticsReviewQueuesPartialUpdateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(llmAnalyticsReviewQueuesPartialUpdateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(llmAnalyticsReviewQueuesPartialUpdateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(llmAnalyticsReviewQueuesPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .describe('User who created this review queue.'),
    team: zod.number(),
})

export const llmAnalyticsScoreDefinitionsListResponseResultsItemConfigOneOneOptionsItemKeyMax = 128

export const llmAnalyticsScoreDefinitionsListResponseResultsItemConfigOneOneOptionsItemLabelMax = 256

export const llmAnalyticsScoreDefinitionsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const llmAnalyticsScoreDefinitionsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const llmAnalyticsScoreDefinitionsListResponseResultsItemCreatedByOneLastNameMax = 150

export const llmAnalyticsScoreDefinitionsListResponseResultsItemCreatedByOneEmailMax = 254

export const LlmAnalyticsScoreDefinitionsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string(),
            description: zod.string(),
            kind: zod
                .enum(['categorical', 'numeric', 'boolean'])
                .describe('* `categorical` - categorical\n* `numeric` - numeric\n* `boolean` - boolean'),
            archived: zod.boolean(),
            current_version: zod.number().describe('Current immutable configuration version number.'),
            config: zod
                .union([
                    zod.object({
                        options: zod
                            .array(
                                zod.object({
                                    key: zod
                                        .string()
                                        .max(
                                            llmAnalyticsScoreDefinitionsListResponseResultsItemConfigOneOneOptionsItemKeyMax
                                        )
                                        .describe(
                                            'Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'
                                        ),
                                    label: zod
                                        .string()
                                        .max(
                                            llmAnalyticsScoreDefinitionsListResponseResultsItemConfigOneOneOptionsItemLabelMax
                                        )
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
                .describe('Current immutable scorer configuration.'),
            created_by: zod
                .object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(llmAnalyticsScoreDefinitionsListResponseResultsItemCreatedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(llmAnalyticsScoreDefinitionsListResponseResultsItemCreatedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(llmAnalyticsScoreDefinitionsListResponseResultsItemCreatedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(llmAnalyticsScoreDefinitionsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
                .nullable()
                .describe('User who created the scorer.'),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
            team: zod.number(),
        })
    ),
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

export const llmAnalyticsScoreDefinitionsRetrieveResponseConfigOneOneOptionsItemKeyMax = 128

export const llmAnalyticsScoreDefinitionsRetrieveResponseConfigOneOneOptionsItemLabelMax = 256

export const llmAnalyticsScoreDefinitionsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsScoreDefinitionsRetrieveResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsScoreDefinitionsRetrieveResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsScoreDefinitionsRetrieveResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsScoreDefinitionsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string(),
    description: zod.string(),
    kind: zod
        .enum(['categorical', 'numeric', 'boolean'])
        .describe('* `categorical` - categorical\n* `numeric` - numeric\n* `boolean` - boolean'),
    archived: zod.boolean(),
    current_version: zod.number().describe('Current immutable configuration version number.'),
    config: zod
        .union([
            zod.object({
                options: zod
                    .array(
                        zod.object({
                            key: zod
                                .string()
                                .max(llmAnalyticsScoreDefinitionsRetrieveResponseConfigOneOneOptionsItemKeyMax)
                                .describe(
                                    'Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'
                                ),
                            label: zod
                                .string()
                                .max(llmAnalyticsScoreDefinitionsRetrieveResponseConfigOneOneOptionsItemLabelMax)
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
        .describe('Current immutable scorer configuration.'),
    created_by: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(llmAnalyticsScoreDefinitionsRetrieveResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(llmAnalyticsScoreDefinitionsRetrieveResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod.string().max(llmAnalyticsScoreDefinitionsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(llmAnalyticsScoreDefinitionsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .nullable()
        .describe('User who created the scorer.'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    team: zod.number(),
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

export const llmAnalyticsScoreDefinitionsPartialUpdateResponseConfigOneOneOptionsItemKeyMax = 128

export const llmAnalyticsScoreDefinitionsPartialUpdateResponseConfigOneOneOptionsItemLabelMax = 256

export const llmAnalyticsScoreDefinitionsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsScoreDefinitionsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsScoreDefinitionsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsScoreDefinitionsPartialUpdateResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsScoreDefinitionsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string(),
    description: zod.string(),
    kind: zod
        .enum(['categorical', 'numeric', 'boolean'])
        .describe('* `categorical` - categorical\n* `numeric` - numeric\n* `boolean` - boolean'),
    archived: zod.boolean(),
    current_version: zod.number().describe('Current immutable configuration version number.'),
    config: zod
        .union([
            zod.object({
                options: zod
                    .array(
                        zod.object({
                            key: zod
                                .string()
                                .max(llmAnalyticsScoreDefinitionsPartialUpdateResponseConfigOneOneOptionsItemKeyMax)
                                .describe(
                                    'Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'
                                ),
                            label: zod
                                .string()
                                .max(llmAnalyticsScoreDefinitionsPartialUpdateResponseConfigOneOneOptionsItemLabelMax)
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
        .describe('Current immutable scorer configuration.'),
    created_by: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(llmAnalyticsScoreDefinitionsPartialUpdateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(llmAnalyticsScoreDefinitionsPartialUpdateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(llmAnalyticsScoreDefinitionsPartialUpdateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(llmAnalyticsScoreDefinitionsPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .nullable()
        .describe('User who created the scorer.'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    team: zod.number(),
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

export const llmAnalyticsScoreDefinitionsNewVersionCreateResponseConfigOneOneOptionsItemKeyMax = 128

export const llmAnalyticsScoreDefinitionsNewVersionCreateResponseConfigOneOneOptionsItemLabelMax = 256

export const llmAnalyticsScoreDefinitionsNewVersionCreateResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsScoreDefinitionsNewVersionCreateResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsScoreDefinitionsNewVersionCreateResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsScoreDefinitionsNewVersionCreateResponseCreatedByOneEmailMax = 254

export const LlmAnalyticsScoreDefinitionsNewVersionCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string(),
    description: zod.string(),
    kind: zod
        .enum(['categorical', 'numeric', 'boolean'])
        .describe('* `categorical` - categorical\n* `numeric` - numeric\n* `boolean` - boolean'),
    archived: zod.boolean(),
    current_version: zod.number().describe('Current immutable configuration version number.'),
    config: zod
        .union([
            zod.object({
                options: zod
                    .array(
                        zod.object({
                            key: zod
                                .string()
                                .max(llmAnalyticsScoreDefinitionsNewVersionCreateResponseConfigOneOneOptionsItemKeyMax)
                                .describe(
                                    'Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'
                                ),
                            label: zod
                                .string()
                                .max(
                                    llmAnalyticsScoreDefinitionsNewVersionCreateResponseConfigOneOneOptionsItemLabelMax
                                )
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
        .describe('Current immutable scorer configuration.'),
    created_by: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(llmAnalyticsScoreDefinitionsNewVersionCreateResponseCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(llmAnalyticsScoreDefinitionsNewVersionCreateResponseCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(llmAnalyticsScoreDefinitionsNewVersionCreateResponseCreatedByOneLastNameMax)
                .optional(),
            email: zod.email().max(llmAnalyticsScoreDefinitionsNewVersionCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .nullable()
        .describe('User who created the scorer.'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    team: zod.number(),
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

export const LlmAnalyticsSentimentCreateResponse = /* @__PURE__ */ zod.object({
    results: zod.record(
        zod.string(),
        zod.object({
            label: zod.string(),
            score: zod.number(),
            scores: zod.record(zod.string(), zod.number()),
            messages: zod.record(
                zod.string(),
                zod.object({
                    label: zod.string(),
                    score: zod.number(),
                    scores: zod.record(zod.string(), zod.number()),
                })
            ),
            message_count: zod.number(),
        })
    ),
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

export const LlmAnalyticsSummarizationCreateResponse = /* @__PURE__ */ zod.object({
    summary: zod
        .object({
            title: zod.string().describe('Concise title (no longer than 10 words) summarizing the trace/event'),
            flow_diagram: zod.string().describe('Mermaid flowchart code showing the main flow'),
            summary_bullets: zod
                .array(
                    zod.object({
                        text: zod.string(),
                        line_refs: zod.string(),
                    })
                )
                .describe('Main summary bullets'),
            interesting_notes: zod
                .array(
                    zod.object({
                        text: zod.string(),
                        line_refs: zod.string(),
                    })
                )
                .describe('Interesting notes (0-2 for minimal, more for detailed)'),
        })
        .describe('Structured AI-generated summary with flow, bullets, and optional notes'),
    text_repr: zod.string().describe('Line-numbered text representation that the summary references'),
    metadata: zod.unknown().optional().describe('Metadata about the summarization'),
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

export const llmAnalyticsSummarizationBatchCheckCreateResponseSummariesItemCachedDefault = true

export const LlmAnalyticsSummarizationBatchCheckCreateResponse = /* @__PURE__ */ zod.object({
    summaries: zod.array(
        zod.object({
            trace_id: zod.string(),
            title: zod.string(),
            cached: zod.boolean().default(llmAnalyticsSummarizationBatchCheckCreateResponseSummariesItemCachedDefault),
        })
    ),
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

export const LlmAnalyticsTextReprCreateResponse = /* @__PURE__ */ zod.object({
    text: zod.string().describe('Generated text representation of the event'),
    metadata: zod
        .object({
            event_type: zod.string().optional(),
            event_id: zod.string().optional(),
            trace_id: zod.string().optional(),
            rendering: zod.string(),
            char_count: zod.number(),
            truncated: zod.boolean(),
            error: zod.string().optional(),
        })
        .describe('Metadata about the text representation'),
})

export const llmAnalyticsTraceReviewsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const llmAnalyticsTraceReviewsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const llmAnalyticsTraceReviewsListResponseResultsItemCreatedByOneLastNameMax = 150

export const llmAnalyticsTraceReviewsListResponseResultsItemCreatedByOneEmailMax = 254

export const llmAnalyticsTraceReviewsListResponseResultsItemReviewedByOneDistinctIdMax = 200

export const llmAnalyticsTraceReviewsListResponseResultsItemReviewedByOneFirstNameMax = 150

export const llmAnalyticsTraceReviewsListResponseResultsItemReviewedByOneLastNameMax = 150

export const llmAnalyticsTraceReviewsListResponseResultsItemReviewedByOneEmailMax = 254

export const llmAnalyticsTraceReviewsListResponseResultsItemScoresItemDefinitionConfigOneOneOptionsItemKeyMax = 128

export const llmAnalyticsTraceReviewsListResponseResultsItemScoresItemDefinitionConfigOneOneOptionsItemLabelMax = 256

export const llmAnalyticsTraceReviewsListResponseResultsItemScoresItemNumericValueRegExp = new RegExp(
    '^-?\\d{0,6}(?:\\.\\d{0,6})?$'
)

export const LlmAnalyticsTraceReviewsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            trace_id: zod.string().describe('Trace ID for the review.'),
            comment: zod.string().nullable().describe('Optional human comment or reasoning for the review.'),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(llmAnalyticsTraceReviewsListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(llmAnalyticsTraceReviewsListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(llmAnalyticsTraceReviewsListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(llmAnalyticsTraceReviewsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            reviewed_by: zod
                .object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod
                        .string()
                        .max(llmAnalyticsTraceReviewsListResponseResultsItemReviewedByOneDistinctIdMax)
                        .nullish(),
                    first_name: zod
                        .string()
                        .max(llmAnalyticsTraceReviewsListResponseResultsItemReviewedByOneFirstNameMax)
                        .optional(),
                    last_name: zod
                        .string()
                        .max(llmAnalyticsTraceReviewsListResponseResultsItemReviewedByOneLastNameMax)
                        .optional(),
                    email: zod.email().max(llmAnalyticsTraceReviewsListResponseResultsItemReviewedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                })
                .describe('User who last saved this review.'),
            scores: zod
                .array(
                    zod.object({
                        id: zod.uuid(),
                        definition_id: zod.uuid().describe('Stable scorer definition ID.'),
                        definition_name: zod.string().describe('Human-readable scorer name.'),
                        definition_kind: zod.string().describe('Scorer kind for this saved score.'),
                        definition_archived: zod.boolean().describe('Whether the scorer is currently archived.'),
                        definition_version_id: zod
                            .uuid()
                            .describe('Immutable scorer version ID used to validate this score.'),
                        definition_version: zod
                            .number()
                            .describe('Immutable scorer version number used to validate this score.'),
                        definition_config: zod
                            .union([
                                zod.object({
                                    options: zod
                                        .array(
                                            zod.object({
                                                key: zod
                                                    .string()
                                                    .max(
                                                        llmAnalyticsTraceReviewsListResponseResultsItemScoresItemDefinitionConfigOneOneOptionsItemKeyMax
                                                    )
                                                    .describe(
                                                        'Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'
                                                    ),
                                                label: zod
                                                    .string()
                                                    .max(
                                                        llmAnalyticsTraceReviewsListResponseResultsItemScoresItemDefinitionConfigOneOneOptionsItemLabelMax
                                                    )
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
                            .describe('Immutable scorer configuration snapshot used to validate this score.'),
                        categorical_values: zod
                            .array(zod.string())
                            .nullable()
                            .describe('Categorical option keys selected for this score.'),
                        numeric_value: zod
                            .string()
                            .regex(llmAnalyticsTraceReviewsListResponseResultsItemScoresItemNumericValueRegExp)
                            .nullable(),
                        boolean_value: zod.boolean().nullable(),
                        created_at: zod.iso.datetime({}),
                        updated_at: zod.iso.datetime({}).nullable(),
                    })
                )
                .describe('Saved scorer values for this review.'),
            team: zod.number(),
        })
    ),
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

export const llmAnalyticsTraceReviewsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsTraceReviewsRetrieveResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsTraceReviewsRetrieveResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsTraceReviewsRetrieveResponseCreatedByOneEmailMax = 254

export const llmAnalyticsTraceReviewsRetrieveResponseReviewedByOneDistinctIdMax = 200

export const llmAnalyticsTraceReviewsRetrieveResponseReviewedByOneFirstNameMax = 150

export const llmAnalyticsTraceReviewsRetrieveResponseReviewedByOneLastNameMax = 150

export const llmAnalyticsTraceReviewsRetrieveResponseReviewedByOneEmailMax = 254

export const llmAnalyticsTraceReviewsRetrieveResponseScoresItemDefinitionConfigOneOneOptionsItemKeyMax = 128

export const llmAnalyticsTraceReviewsRetrieveResponseScoresItemDefinitionConfigOneOneOptionsItemLabelMax = 256

export const llmAnalyticsTraceReviewsRetrieveResponseScoresItemNumericValueRegExp = new RegExp(
    '^-?\\d{0,6}(?:\\.\\d{0,6})?$'
)

export const LlmAnalyticsTraceReviewsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    trace_id: zod.string().describe('Trace ID for the review.'),
    comment: zod.string().nullable().describe('Optional human comment or reasoning for the review.'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(llmAnalyticsTraceReviewsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(llmAnalyticsTraceReviewsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(llmAnalyticsTraceReviewsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(llmAnalyticsTraceReviewsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    reviewed_by: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(llmAnalyticsTraceReviewsRetrieveResponseReviewedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(llmAnalyticsTraceReviewsRetrieveResponseReviewedByOneFirstNameMax).optional(),
            last_name: zod.string().max(llmAnalyticsTraceReviewsRetrieveResponseReviewedByOneLastNameMax).optional(),
            email: zod.email().max(llmAnalyticsTraceReviewsRetrieveResponseReviewedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .describe('User who last saved this review.'),
    scores: zod
        .array(
            zod.object({
                id: zod.uuid(),
                definition_id: zod.uuid().describe('Stable scorer definition ID.'),
                definition_name: zod.string().describe('Human-readable scorer name.'),
                definition_kind: zod.string().describe('Scorer kind for this saved score.'),
                definition_archived: zod.boolean().describe('Whether the scorer is currently archived.'),
                definition_version_id: zod.uuid().describe('Immutable scorer version ID used to validate this score.'),
                definition_version: zod
                    .number()
                    .describe('Immutable scorer version number used to validate this score.'),
                definition_config: zod
                    .union([
                        zod.object({
                            options: zod
                                .array(
                                    zod.object({
                                        key: zod
                                            .string()
                                            .max(
                                                llmAnalyticsTraceReviewsRetrieveResponseScoresItemDefinitionConfigOneOneOptionsItemKeyMax
                                            )
                                            .describe(
                                                'Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'
                                            ),
                                        label: zod
                                            .string()
                                            .max(
                                                llmAnalyticsTraceReviewsRetrieveResponseScoresItemDefinitionConfigOneOneOptionsItemLabelMax
                                            )
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
                    .describe('Immutable scorer configuration snapshot used to validate this score.'),
                categorical_values: zod
                    .array(zod.string())
                    .nullable()
                    .describe('Categorical option keys selected for this score.'),
                numeric_value: zod
                    .string()
                    .regex(llmAnalyticsTraceReviewsRetrieveResponseScoresItemNumericValueRegExp)
                    .nullable(),
                boolean_value: zod.boolean().nullable(),
                created_at: zod.iso.datetime({}),
                updated_at: zod.iso.datetime({}).nullable(),
            })
        )
        .describe('Saved scorer values for this review.'),
    team: zod.number(),
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

export const llmAnalyticsTraceReviewsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const llmAnalyticsTraceReviewsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const llmAnalyticsTraceReviewsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const llmAnalyticsTraceReviewsPartialUpdateResponseCreatedByOneEmailMax = 254

export const llmAnalyticsTraceReviewsPartialUpdateResponseReviewedByOneDistinctIdMax = 200

export const llmAnalyticsTraceReviewsPartialUpdateResponseReviewedByOneFirstNameMax = 150

export const llmAnalyticsTraceReviewsPartialUpdateResponseReviewedByOneLastNameMax = 150

export const llmAnalyticsTraceReviewsPartialUpdateResponseReviewedByOneEmailMax = 254

export const llmAnalyticsTraceReviewsPartialUpdateResponseScoresItemDefinitionConfigOneOneOptionsItemKeyMax = 128

export const llmAnalyticsTraceReviewsPartialUpdateResponseScoresItemDefinitionConfigOneOneOptionsItemLabelMax = 256

export const llmAnalyticsTraceReviewsPartialUpdateResponseScoresItemNumericValueRegExp = new RegExp(
    '^-?\\d{0,6}(?:\\.\\d{0,6})?$'
)

export const LlmAnalyticsTraceReviewsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    trace_id: zod.string().describe('Trace ID for the review.'),
    comment: zod.string().nullable().describe('Optional human comment or reasoning for the review.'),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(llmAnalyticsTraceReviewsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(llmAnalyticsTraceReviewsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(llmAnalyticsTraceReviewsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(llmAnalyticsTraceReviewsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    reviewed_by: zod
        .object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(llmAnalyticsTraceReviewsPartialUpdateResponseReviewedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(llmAnalyticsTraceReviewsPartialUpdateResponseReviewedByOneFirstNameMax)
                .optional(),
            last_name: zod
                .string()
                .max(llmAnalyticsTraceReviewsPartialUpdateResponseReviewedByOneLastNameMax)
                .optional(),
            email: zod.email().max(llmAnalyticsTraceReviewsPartialUpdateResponseReviewedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        })
        .describe('User who last saved this review.'),
    scores: zod
        .array(
            zod.object({
                id: zod.uuid(),
                definition_id: zod.uuid().describe('Stable scorer definition ID.'),
                definition_name: zod.string().describe('Human-readable scorer name.'),
                definition_kind: zod.string().describe('Scorer kind for this saved score.'),
                definition_archived: zod.boolean().describe('Whether the scorer is currently archived.'),
                definition_version_id: zod.uuid().describe('Immutable scorer version ID used to validate this score.'),
                definition_version: zod
                    .number()
                    .describe('Immutable scorer version number used to validate this score.'),
                definition_config: zod
                    .union([
                        zod.object({
                            options: zod
                                .array(
                                    zod.object({
                                        key: zod
                                            .string()
                                            .max(
                                                llmAnalyticsTraceReviewsPartialUpdateResponseScoresItemDefinitionConfigOneOneOptionsItemKeyMax
                                            )
                                            .describe(
                                                'Stable option key. Use lowercase letters, numbers, underscores, or hyphens.'
                                            ),
                                        label: zod
                                            .string()
                                            .max(
                                                llmAnalyticsTraceReviewsPartialUpdateResponseScoresItemDefinitionConfigOneOneOptionsItemLabelMax
                                            )
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
                    .describe('Immutable scorer configuration snapshot used to validate this score.'),
                categorical_values: zod
                    .array(zod.string())
                    .nullable()
                    .describe('Categorical option keys selected for this score.'),
                numeric_value: zod
                    .string()
                    .regex(llmAnalyticsTraceReviewsPartialUpdateResponseScoresItemNumericValueRegExp)
                    .nullable(),
                boolean_value: zod.boolean().nullable(),
                created_at: zod.iso.datetime({}),
                updated_at: zod.iso.datetime({}).nullable(),
            })
        )
        .describe('Saved scorer values for this review.'),
    team: zod.number(),
})

export const llmPromptsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const llmPromptsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const llmPromptsListResponseResultsItemCreatedByOneLastNameMax = 150

export const llmPromptsListResponseResultsItemCreatedByOneEmailMax = 254

export const LlmPromptsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
            prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
            version: zod.number(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(llmPromptsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(llmPromptsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(llmPromptsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(llmPromptsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}),
            deleted: zod.boolean(),
            is_latest: zod.boolean(),
            latest_version: zod.number(),
            version_count: zod.number(),
            first_version_created_at: zod.string(),
            prompt_preview: zod.string(),
            prompt_size_bytes: zod.number(),
        })
    ),
})

export const llmPromptsCreateBodyNameMax = 255

export const LlmPromptsCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(llmPromptsCreateBodyNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
})

export const LlmPromptsNameRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string(),
    prompt: zod.unknown(),
    version: zod.number(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    deleted: zod.boolean(),
    is_latest: zod.boolean(),
    latest_version: zod.number(),
    version_count: zod.number(),
    first_version_created_at: zod.iso.datetime({}),
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

export const llmPromptsNamePartialUpdateResponseNameMax = 255

export const llmPromptsNamePartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const llmPromptsNamePartialUpdateResponseCreatedByOneFirstNameMax = 150

export const llmPromptsNamePartialUpdateResponseCreatedByOneLastNameMax = 150

export const llmPromptsNamePartialUpdateResponseCreatedByOneEmailMax = 254

export const LlmPromptsNamePartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(llmPromptsNamePartialUpdateResponseNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
    version: zod.number(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(llmPromptsNamePartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(llmPromptsNamePartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(llmPromptsNamePartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(llmPromptsNamePartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    deleted: zod.boolean(),
    is_latest: zod.boolean(),
    latest_version: zod.number(),
    version_count: zod.number(),
    first_version_created_at: zod.string(),
})

export const llmPromptsNameArchiveCreateBodyNameMax = 255

export const LlmPromptsNameArchiveCreateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(llmPromptsNameArchiveCreateBodyNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
})

export const llmPromptsNameArchiveCreateResponseNameMax = 255

export const llmPromptsNameArchiveCreateResponseCreatedByOneDistinctIdMax = 200

export const llmPromptsNameArchiveCreateResponseCreatedByOneFirstNameMax = 150

export const llmPromptsNameArchiveCreateResponseCreatedByOneLastNameMax = 150

export const llmPromptsNameArchiveCreateResponseCreatedByOneEmailMax = 254

export const LlmPromptsNameArchiveCreateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod
        .string()
        .max(llmPromptsNameArchiveCreateResponseNameMax)
        .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
    prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
    version: zod.number(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(llmPromptsNameArchiveCreateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(llmPromptsNameArchiveCreateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(llmPromptsNameArchiveCreateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(llmPromptsNameArchiveCreateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    deleted: zod.boolean(),
    is_latest: zod.boolean(),
    latest_version: zod.number(),
    version_count: zod.number(),
    first_version_created_at: zod.string(),
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

export const llmPromptsResolveNameRetrieveResponsePromptNameMax = 255

export const llmPromptsResolveNameRetrieveResponsePromptCreatedByOneDistinctIdMax = 200

export const llmPromptsResolveNameRetrieveResponsePromptCreatedByOneFirstNameMax = 150

export const llmPromptsResolveNameRetrieveResponsePromptCreatedByOneLastNameMax = 150

export const llmPromptsResolveNameRetrieveResponsePromptCreatedByOneEmailMax = 254

export const llmPromptsResolveNameRetrieveResponseVersionsItemCreatedByOneDistinctIdMax = 200

export const llmPromptsResolveNameRetrieveResponseVersionsItemCreatedByOneFirstNameMax = 150

export const llmPromptsResolveNameRetrieveResponseVersionsItemCreatedByOneLastNameMax = 150

export const llmPromptsResolveNameRetrieveResponseVersionsItemCreatedByOneEmailMax = 254

export const LlmPromptsResolveNameRetrieveResponse = /* @__PURE__ */ zod.object({
    prompt: zod.object({
        id: zod.uuid(),
        name: zod
            .string()
            .max(llmPromptsResolveNameRetrieveResponsePromptNameMax)
            .describe('Unique prompt name using letters, numbers, hyphens, and underscores only.'),
        prompt: zod.unknown().describe('Prompt payload as JSON or string data.'),
        version: zod.number(),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod
                .string()
                .max(llmPromptsResolveNameRetrieveResponsePromptCreatedByOneDistinctIdMax)
                .nullish(),
            first_name: zod
                .string()
                .max(llmPromptsResolveNameRetrieveResponsePromptCreatedByOneFirstNameMax)
                .optional(),
            last_name: zod.string().max(llmPromptsResolveNameRetrieveResponsePromptCreatedByOneLastNameMax).optional(),
            email: zod.email().max(llmPromptsResolveNameRetrieveResponsePromptCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        created_at: zod.iso.datetime({}),
        updated_at: zod.iso.datetime({}),
        deleted: zod.boolean(),
        is_latest: zod.boolean(),
        latest_version: zod.number(),
        version_count: zod.number(),
        first_version_created_at: zod.string(),
    }),
    versions: zod.array(
        zod.object({
            id: zod.uuid(),
            version: zod.number(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(llmPromptsResolveNameRetrieveResponseVersionsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(llmPromptsResolveNameRetrieveResponseVersionsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(llmPromptsResolveNameRetrieveResponseVersionsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(llmPromptsResolveNameRetrieveResponseVersionsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            created_at: zod.iso.datetime({}),
            is_latest: zod.boolean(),
        })
    ),
    has_more: zod.boolean(),
})

export const datasetItemsListResponseResultsItemRefTraceIdMax = 255

export const datasetItemsListResponseResultsItemRefSourceIdMax = 255

export const datasetItemsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const datasetItemsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const datasetItemsListResponseResultsItemCreatedByOneLastNameMax = 150

export const datasetItemsListResponseResultsItemCreatedByOneEmailMax = 254

export const DatasetItemsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            dataset: zod.uuid(),
            input: zod.unknown().nullish(),
            output: zod.unknown().nullish(),
            metadata: zod.unknown().nullish(),
            ref_trace_id: zod.string().max(datasetItemsListResponseResultsItemRefTraceIdMax).nullish(),
            ref_timestamp: zod.iso.datetime({}).nullish(),
            ref_source_id: zod.string().max(datasetItemsListResponseResultsItemRefSourceIdMax).nullish(),
            deleted: zod.boolean().nullish(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(datasetItemsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(datasetItemsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(datasetItemsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(datasetItemsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            team: zod.number(),
        })
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

export const datasetItemsRetrieveResponseRefTraceIdMax = 255

export const datasetItemsRetrieveResponseRefSourceIdMax = 255

export const datasetItemsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const datasetItemsRetrieveResponseCreatedByOneFirstNameMax = 150

export const datasetItemsRetrieveResponseCreatedByOneLastNameMax = 150

export const datasetItemsRetrieveResponseCreatedByOneEmailMax = 254

export const DatasetItemsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    dataset: zod.uuid(),
    input: zod.unknown().nullish(),
    output: zod.unknown().nullish(),
    metadata: zod.unknown().nullish(),
    ref_trace_id: zod.string().max(datasetItemsRetrieveResponseRefTraceIdMax).nullish(),
    ref_timestamp: zod.iso.datetime({}).nullish(),
    ref_source_id: zod.string().max(datasetItemsRetrieveResponseRefSourceIdMax).nullish(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(datasetItemsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(datasetItemsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(datasetItemsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(datasetItemsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    team: zod.number(),
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

export const datasetItemsUpdateResponseRefTraceIdMax = 255

export const datasetItemsUpdateResponseRefSourceIdMax = 255

export const datasetItemsUpdateResponseCreatedByOneDistinctIdMax = 200

export const datasetItemsUpdateResponseCreatedByOneFirstNameMax = 150

export const datasetItemsUpdateResponseCreatedByOneLastNameMax = 150

export const datasetItemsUpdateResponseCreatedByOneEmailMax = 254

export const DatasetItemsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    dataset: zod.uuid(),
    input: zod.unknown().nullish(),
    output: zod.unknown().nullish(),
    metadata: zod.unknown().nullish(),
    ref_trace_id: zod.string().max(datasetItemsUpdateResponseRefTraceIdMax).nullish(),
    ref_timestamp: zod.iso.datetime({}).nullish(),
    ref_source_id: zod.string().max(datasetItemsUpdateResponseRefSourceIdMax).nullish(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(datasetItemsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(datasetItemsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(datasetItemsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(datasetItemsUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    team: zod.number(),
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

export const datasetItemsPartialUpdateResponseRefTraceIdMax = 255

export const datasetItemsPartialUpdateResponseRefSourceIdMax = 255

export const datasetItemsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const datasetItemsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const datasetItemsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const datasetItemsPartialUpdateResponseCreatedByOneEmailMax = 254

export const DatasetItemsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    dataset: zod.uuid(),
    input: zod.unknown().nullish(),
    output: zod.unknown().nullish(),
    metadata: zod.unknown().nullish(),
    ref_trace_id: zod.string().max(datasetItemsPartialUpdateResponseRefTraceIdMax).nullish(),
    ref_timestamp: zod.iso.datetime({}).nullish(),
    ref_source_id: zod.string().max(datasetItemsPartialUpdateResponseRefSourceIdMax).nullish(),
    deleted: zod.boolean().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(datasetItemsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(datasetItemsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(datasetItemsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(datasetItemsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    team: zod.number(),
})

export const datasetsListResponseResultsItemNameMax = 400

export const datasetsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const datasetsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const datasetsListResponseResultsItemCreatedByOneLastNameMax = 150

export const datasetsListResponseResultsItemCreatedByOneEmailMax = 254

export const DatasetsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            name: zod.string().max(datasetsListResponseResultsItemNameMax),
            description: zod.string().nullish(),
            metadata: zod.unknown().nullish(),
            created_at: zod.iso.datetime({}),
            updated_at: zod.iso.datetime({}).nullable(),
            deleted: zod.boolean().nullish(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod.string().max(datasetsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                first_name: zod.string().max(datasetsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(datasetsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(datasetsListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            team: zod.number(),
        })
    ),
})

export const datasetsCreateBodyNameMax = 400

export const DatasetsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(datasetsCreateBodyNameMax),
    description: zod.string().nullish(),
    metadata: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
})

export const datasetsRetrieveResponseNameMax = 400

export const datasetsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const datasetsRetrieveResponseCreatedByOneFirstNameMax = 150

export const datasetsRetrieveResponseCreatedByOneLastNameMax = 150

export const datasetsRetrieveResponseCreatedByOneEmailMax = 254

export const DatasetsRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(datasetsRetrieveResponseNameMax),
    description: zod.string().nullish(),
    metadata: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    deleted: zod.boolean().nullish(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(datasetsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(datasetsRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(datasetsRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(datasetsRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    team: zod.number(),
})

export const datasetsUpdateBodyNameMax = 400

export const DatasetsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(datasetsUpdateBodyNameMax),
    description: zod.string().nullish(),
    metadata: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
})

export const datasetsUpdateResponseNameMax = 400

export const datasetsUpdateResponseCreatedByOneDistinctIdMax = 200

export const datasetsUpdateResponseCreatedByOneFirstNameMax = 150

export const datasetsUpdateResponseCreatedByOneLastNameMax = 150

export const datasetsUpdateResponseCreatedByOneEmailMax = 254

export const DatasetsUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(datasetsUpdateResponseNameMax),
    description: zod.string().nullish(),
    metadata: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    deleted: zod.boolean().nullish(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(datasetsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(datasetsUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(datasetsUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(datasetsUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    team: zod.number(),
})

export const datasetsPartialUpdateBodyNameMax = 400

export const DatasetsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(datasetsPartialUpdateBodyNameMax).optional(),
    description: zod.string().nullish(),
    metadata: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
})

export const datasetsPartialUpdateResponseNameMax = 400

export const datasetsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const datasetsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const datasetsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const datasetsPartialUpdateResponseCreatedByOneEmailMax = 254

export const DatasetsPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    name: zod.string().max(datasetsPartialUpdateResponseNameMax),
    description: zod.string().nullish(),
    metadata: zod.unknown().nullish(),
    created_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}).nullable(),
    deleted: zod.boolean().nullish(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(datasetsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(datasetsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(datasetsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(datasetsPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    team: zod.number(),
})
