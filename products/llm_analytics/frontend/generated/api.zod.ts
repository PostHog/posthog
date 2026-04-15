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
export const llmAnalyticsClusteringJobsUpdateBodyNameMax = 100

export const LlmAnalyticsClusteringJobsUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsClusteringJobsUpdateBodyNameMax),
    analysis_level: zod.enum(['trace', 'generation']).describe('* `trace` - trace\n* `generation` - generation'),
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
        .enum(['trace', 'generation'])
        .optional()
        .describe('* `trace` - trace\n* `generation` - generation'),
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
