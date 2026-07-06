/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 57 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Return a structured personal LLM spend analysis for the requesting user. Pass `date_from` / `date_to` (absolute like `2026-04-23` or relative like `-7d`) to bound the window — defaults to the last 30 days, max 90 days. The `product=<ai_product>` query param is required and scopes the tool / model / day / trace breakdowns to a single product; supported values: posthog_code. `by_product` is always returned for cross-product visibility. `by_day` returns a day-ascending spend series for the scoped product. Use `refresh=true` to bypass the 5-minute response cache.
 */
export const llmAnalyticsPersonalSpendListQueryDateFromDefault = `-30d`
export const llmAnalyticsPersonalSpendListQueryDateFromMax = 32

export const llmAnalyticsPersonalSpendListQueryDateToMax = 32

export const llmAnalyticsPersonalSpendListQueryLimitDefault = 50
export const llmAnalyticsPersonalSpendListQueryLimitMax = 200

export const llmAnalyticsPersonalSpendListQueryProductMax = 64

export const llmAnalyticsPersonalSpendListQueryRefreshDefault = false

export const LlmAnalyticsPersonalSpendListQueryParams = /* @__PURE__ */ zod.object({
    date_from: zod
        .string()
        .min(1)
        .max(llmAnalyticsPersonalSpendListQueryDateFromMax)
        .default(llmAnalyticsPersonalSpendListQueryDateFromDefault)
        .describe(
            'Start of the spend window. Accepts absolute dates (`2026-04-23`) or relative strings (`-7d`, `-1m`, etc.) — same parser used elsewhere in PostHog. Defaults to `-30d`. The window between `date_from` and `date_to` cannot exceed 90 days.'
        ),
    date_to: zod
        .string()
        .max(llmAnalyticsPersonalSpendListQueryDateToMax)
        .nullish()
        .describe('End of the spend window. Accepts the same formats as `date_from`. Defaults to `now` when omitted.'),
    limit: zod
        .number()
        .min(1)
        .max(llmAnalyticsPersonalSpendListQueryLimitMax)
        .default(llmAnalyticsPersonalSpendListQueryLimitDefault)
        .describe(
            'Maximum number of rows to return per breakdown (1-200, defaults to 50). Each breakdown returns up to this many rows ordered by cost descending. Per-breakdown `truncated: true` indicates more rows exist beyond the limit.'
        ),
    product: zod
        .string()
        .min(1)
        .max(llmAnalyticsPersonalSpendListQueryProductMax)
        .describe(
            'Required `ai_product` key to scope the tool / model / trace breakdowns to a single product. Only the following products are currently supported: posthog_code.'
        ),
    refresh: zod
        .boolean()
        .default(llmAnalyticsPersonalSpendListQueryRefreshDefault)
        .describe('If true, bypass the result cache and re-run the underlying queries against ClickHouse.'),
})

/**
 * Create a new evaluation run.
 *
 * This endpoint validates the request and enqueues a Temporal workflow
 * to asynchronously execute the evaluation.
 */
export const EvaluationRunsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const evaluationRunsCreateBodyEventDefault = `$ai_generation`

export const EvaluationRunsCreateBody = /* @__PURE__ */ zod.object({
    evaluation_id: zod.string().describe('UUID of the evaluation to run.'),
    target_event_id: zod.string().describe('UUID of the $ai_generation event to evaluate.'),
    timestamp: zod.iso
        .datetime({ offset: true })
        .describe('ISO 8601 timestamp of the target event (needed for efficient ClickHouse lookup).'),
    event: zod
        .string()
        .default(evaluationRunsCreateBodyEventDefault)
        .describe("Event name. Defaults to '$ai_generation'."),
    distinct_id: zod.string().nullish().describe('Distinct ID of the event (optional, improves lookup performance).'),
})

export const EvaluationsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EvaluationsListQueryParams = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Filter by enabled status'),
    evaluation_type: zod
        .enum(['hog', 'llm_judge', 'sentiment'])
        .optional()
        .describe(
            'Filter by evaluation type\n\n* `llm_judge` - LLM as a judge\n* `hog` - Hog\n* `sentiment` - Sentiment analysis'
        ),
    id__in: zod.array(zod.string()).optional().describe('Multiple values may be separated by commas.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .array(zod.string())
        .optional()
        .describe(
            'Ordering\n\n* `created_at` - Created At\n* `-created_at` - Created At (descending)\n* `updated_at` - Updated At\n* `-updated_at` - Updated At (descending)\n* `name` - Name\n* `-name` - Name (descending)'
        ),
    search: zod.string().optional().describe('Search in name or description'),
})

export const EvaluationsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const evaluationsCreateBodyNameMax = 400

export const evaluationsCreateBodyEvaluationConfigThreeSourceDefault = `user_messages`
export const evaluationsCreateBodyOutputConfigAllowsNaDefault = false
export const evaluationsCreateBodyConditionsItemIdMax = 100

export const evaluationsCreateBodyConditionsItemRolloutPercentageDefault = 100
export const evaluationsCreateBodyConditionsItemRolloutPercentageMin = 0
export const evaluationsCreateBodyConditionsItemRolloutPercentageMax = 100

export const evaluationsCreateBodyTargetConfigWindowSecondsDefault = 1800
export const evaluationsCreateBodyTargetConfigWindowSecondsMin = 10
export const evaluationsCreateBodyTargetConfigWindowSecondsMax = 7200

export const evaluationsCreateBodyModelConfigurationOneModelMax = 100

export const EvaluationsCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(evaluationsCreateBodyNameMax).describe('Name of the evaluation.'),
    description: zod.string().optional().describe('Optional description of what this evaluation checks.'),
    enabled: zod
        .boolean()
        .optional()
        .describe('Whether the evaluation runs automatically on new $ai_generation events.'),
    evaluation_type: zod
        .enum(['llm_judge', 'hog', 'sentiment'])
        .describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog\n* `sentiment` - Sentiment analysis')
        .describe(
            "'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code; 'sentiment' classifies user-message sentiment.\n\n* `llm_judge` - LLM as a judge\n* `hog` - Hog\n* `sentiment` - Sentiment analysis"
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
            zod.object({
                source: zod
                    .enum(['user_messages'])
                    .default(evaluationsCreateBodyEvaluationConfigThreeSourceDefault)
                    .describe('Classify sentiment from user messages in the generation input.'),
            }),
        ])
        .optional()
        .describe(
            "Configuration dict. For 'llm_judge': {prompt}; for 'hog': {source}; for 'sentiment': {source: 'user_messages'}."
        ),
    output_type: zod
        .enum(['boolean', 'sentiment'])
        .describe('* `boolean` - Boolean (Pass/Fail)\n* `sentiment` - Sentiment')
        .describe(
            "Output format. Use 'boolean' for pass/fail evaluations and 'sentiment' for sentiment analysis.\n\n* `boolean` - Boolean (Pass/Fail)\n* `sentiment` - Sentiment"
        ),
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
        .array(
            zod
                .object({
                    id: zod
                        .string()
                        .max(evaluationsCreateBodyConditionsItemIdMax)
                        .describe('Stable identifier for this condition set.'),
                    rollout_percentage: zod
                        .number()
                        .min(evaluationsCreateBodyConditionsItemRolloutPercentageMin)
                        .max(evaluationsCreateBodyConditionsItemRolloutPercentageMax)
                        .default(evaluationsCreateBodyConditionsItemRolloutPercentageDefault)
                        .describe(
                            'Percentage (0-100) of matching events to sample for this evaluation. Defaults to 100.'
                        ),
                    properties: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            'Property filters (event or person) that scope which generations match this condition set.'
                        ),
                })
                .describe('A trigger condition set controlling which generations an evaluation runs on.')
        )
        .optional()
        .describe(
            'Trigger conditions that filter which events are evaluated. OR between condition sets, AND within each. Each set is {id, rollout_percentage, properties[]} — `rollout_percentage` (0-100, defaults to 100) is the sampling field the dispatcher reads.'
        ),
    target: zod
        .enum(['generation', 'trace'])
        .describe('* `generation` - Generation\n* `trace` - Trace')
        .optional()
        .describe(
            "What the evaluation runs on. 'generation' evaluates each matching $ai_generation event individually. 'trace' evaluates the whole trace once: the first matching generation schedules a run that waits for the trace to settle, then evaluates all of its events together. Condition filters still match individual generations — a trace is evaluated when any of its generations matches, and sampling applies per trace.\n\n* `generation` - Generation\n* `trace` - Trace"
        ),
    target_config: zod
        .object({
            window_seconds: zod
                .number()
                .min(evaluationsCreateBodyTargetConfigWindowSecondsMin)
                .max(evaluationsCreateBodyTargetConfigWindowSecondsMax)
                .default(evaluationsCreateBodyTargetConfigWindowSecondsDefault)
                .describe(
                    "For 'trace' target: seconds to wait after the first matching generation before evaluating the whole trace. Captured when the run is scheduled — editing it does not change trace runs already in flight."
                ),
        })
        .optional()
        .describe("Target-specific config. For 'trace' target: {window_seconds}. Empty for 'generation'."),
    model_configuration: zod
        .union([
            zod
                .object({
                    provider: zod
                        .enum([
                            'openai',
                            'anthropic',
                            'gemini',
                            'openrouter',
                            'fireworks',
                            'azure_openai',
                            'together_ai',
                            'minimax',
                            'zeabur',
                        ])
                        .describe(
                            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks\n* `azure_openai` - Azure OpenAI\n* `together_ai` - Together AI\n* `minimax` - MiniMax\n* `zeabur` - Zeabur AI Hub'
                        ),
                    model: zod.string().max(evaluationsCreateBodyModelConfigurationOneModelMax),
                    provider_key_id: zod
                        .string()
                        .nullish()
                        .describe(
                            'Team provider key to run this eval with (same provider as `provider`). Leave null only for brief pre-key testing; real evals should set it.'
                        ),
                    provider_key_name: zod.string().nullish(),
                })
                .describe('Nested serializer for model configuration.'),
            zod.null(),
        ])
        .optional(),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the evaluation.'),
})

export const EvaluationsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const EvaluationsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const evaluationsPartialUpdateBodyNameMax = 400

export const evaluationsPartialUpdateBodyEvaluationConfigThreeSourceDefault = `user_messages`
export const evaluationsPartialUpdateBodyOutputConfigAllowsNaDefault = false
export const evaluationsPartialUpdateBodyConditionsItemIdMax = 100

export const evaluationsPartialUpdateBodyConditionsItemRolloutPercentageDefault = 100
export const evaluationsPartialUpdateBodyConditionsItemRolloutPercentageMin = 0
export const evaluationsPartialUpdateBodyConditionsItemRolloutPercentageMax = 100

export const evaluationsPartialUpdateBodyTargetConfigWindowSecondsDefault = 1800
export const evaluationsPartialUpdateBodyTargetConfigWindowSecondsMin = 10
export const evaluationsPartialUpdateBodyTargetConfigWindowSecondsMax = 7200

export const evaluationsPartialUpdateBodyModelConfigurationOneModelMax = 100

export const EvaluationsPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(evaluationsPartialUpdateBodyNameMax).optional().describe('Name of the evaluation.'),
    description: zod.string().optional().describe('Optional description of what this evaluation checks.'),
    enabled: zod
        .boolean()
        .optional()
        .describe('Whether the evaluation runs automatically on new $ai_generation events.'),
    evaluation_type: zod
        .enum(['llm_judge', 'hog', 'sentiment'])
        .describe('* `llm_judge` - LLM as a judge\n* `hog` - Hog\n* `sentiment` - Sentiment analysis')
        .optional()
        .describe(
            "'llm_judge' uses an LLM to score outputs against a prompt; 'hog' runs deterministic Hog code; 'sentiment' classifies user-message sentiment.\n\n* `llm_judge` - LLM as a judge\n* `hog` - Hog\n* `sentiment` - Sentiment analysis"
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
            zod.object({
                source: zod
                    .enum(['user_messages'])
                    .default(evaluationsPartialUpdateBodyEvaluationConfigThreeSourceDefault)
                    .describe('Classify sentiment from user messages in the generation input.'),
            }),
        ])
        .optional()
        .describe(
            "Configuration dict. For 'llm_judge': {prompt}; for 'hog': {source}; for 'sentiment': {source: 'user_messages'}."
        ),
    output_type: zod
        .enum(['boolean', 'sentiment'])
        .describe('* `boolean` - Boolean (Pass/Fail)\n* `sentiment` - Sentiment')
        .optional()
        .describe(
            "Output format. Use 'boolean' for pass/fail evaluations and 'sentiment' for sentiment analysis.\n\n* `boolean` - Boolean (Pass/Fail)\n* `sentiment` - Sentiment"
        ),
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
        .array(
            zod
                .object({
                    id: zod
                        .string()
                        .max(evaluationsPartialUpdateBodyConditionsItemIdMax)
                        .describe('Stable identifier for this condition set.'),
                    rollout_percentage: zod
                        .number()
                        .min(evaluationsPartialUpdateBodyConditionsItemRolloutPercentageMin)
                        .max(evaluationsPartialUpdateBodyConditionsItemRolloutPercentageMax)
                        .default(evaluationsPartialUpdateBodyConditionsItemRolloutPercentageDefault)
                        .describe(
                            'Percentage (0-100) of matching events to sample for this evaluation. Defaults to 100.'
                        ),
                    properties: zod
                        .array(zod.record(zod.string(), zod.unknown()))
                        .optional()
                        .describe(
                            'Property filters (event or person) that scope which generations match this condition set.'
                        ),
                })
                .describe('A trigger condition set controlling which generations an evaluation runs on.')
        )
        .optional()
        .describe(
            'Trigger conditions that filter which events are evaluated. OR between condition sets, AND within each. Each set is {id, rollout_percentage, properties[]} — `rollout_percentage` (0-100, defaults to 100) is the sampling field the dispatcher reads.'
        ),
    target: zod
        .enum(['generation', 'trace'])
        .describe('* `generation` - Generation\n* `trace` - Trace')
        .optional()
        .describe(
            "What the evaluation runs on. 'generation' evaluates each matching $ai_generation event individually. 'trace' evaluates the whole trace once: the first matching generation schedules a run that waits for the trace to settle, then evaluates all of its events together. Condition filters still match individual generations — a trace is evaluated when any of its generations matches, and sampling applies per trace.\n\n* `generation` - Generation\n* `trace` - Trace"
        ),
    target_config: zod
        .object({
            window_seconds: zod
                .number()
                .min(evaluationsPartialUpdateBodyTargetConfigWindowSecondsMin)
                .max(evaluationsPartialUpdateBodyTargetConfigWindowSecondsMax)
                .default(evaluationsPartialUpdateBodyTargetConfigWindowSecondsDefault)
                .describe(
                    "For 'trace' target: seconds to wait after the first matching generation before evaluating the whole trace. Captured when the run is scheduled — editing it does not change trace runs already in flight."
                ),
        })
        .optional()
        .describe("Target-specific config. For 'trace' target: {window_seconds}. Empty for 'generation'."),
    model_configuration: zod
        .union([
            zod
                .object({
                    provider: zod
                        .enum([
                            'openai',
                            'anthropic',
                            'gemini',
                            'openrouter',
                            'fireworks',
                            'azure_openai',
                            'together_ai',
                            'minimax',
                            'zeabur',
                        ])
                        .describe(
                            '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks\n* `azure_openai` - Azure OpenAI\n* `together_ai` - Together AI\n* `minimax` - MiniMax\n* `zeabur` - Zeabur AI Hub'
                        ),
                    model: zod.string().max(evaluationsPartialUpdateBodyModelConfigurationOneModelMax),
                    provider_key_id: zod
                        .string()
                        .nullish()
                        .describe(
                            'Team provider key to run this eval with (same provider as `provider`). Leave null only for brief pre-key testing; real evals should set it.'
                        ),
                    provider_key_name: zod.string().nullish(),
                })
                .describe('Nested serializer for model configuration.'),
            zod.null(),
        ])
        .optional(),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete the evaluation.'),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const EvaluationsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Test Hog evaluation code against sample events without saving.
 */
export const EvaluationsTestHogCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
 * Team-level clustering configuration (event filters for automated pipelines).
 */
export const LlmAnalyticsClusteringConfigListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Team-level clustering configuration (event filters for automated pipelines).
 */
export const LlmAnalyticsClusteringConfigSetEventFiltersCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsClusteringConfigSetEventFiltersCreateBody = /* @__PURE__ */ zod.object({
    event_filters: zod
        .array(zod.record(zod.string(), zod.unknown()))
        .describe(
            'PostHog property filters to save for automated clustering jobs. Pass an empty array to clear filters.'
        ),
})

/**
 * CRUD for clustering job configurations (max 10 per team).
 */
export const LlmAnalyticsClusteringJobsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsClusteringJobsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * CRUD for clustering job configurations (max 10 per team).
 */
export const LlmAnalyticsClusteringJobsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
 * CRUD for clustering job configurations (max 10 per team).
 */
export const LlmAnalyticsClusteringJobsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this clustering job.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * CRUD for clustering job configurations (max 10 per team).
 */
export const LlmAnalyticsClusteringJobsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this clustering job.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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
 * CRUD for clustering job configurations (max 10 per team).
 */
export const LlmAnalyticsClusteringJobsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this clustering job.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Get the evaluation config for this team
 */
export const LlmAnalyticsEvaluationConfigRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Set the active provider key for evaluations
 */
export const LlmAnalyticsEvaluationConfigSetActiveKeyCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsEvaluationConfigSetActiveKeyCreateBody = /* @__PURE__ */ zod.object({
    key_id: zod
        .string()
        .describe(
            "UUID of an existing LLM provider key (state must be 'ok') to mark as the active key for running llm_judge evaluations team-wide."
        ),
})

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const LlmAnalyticsEvaluationReportsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsEvaluationReportsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const LlmAnalyticsEvaluationReportsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsEvaluationReportsCreateBodyTimezoneNameMax = 64

export const llmAnalyticsEvaluationReportsCreateBodyMaxSampleSizeMin = -2147483648
export const llmAnalyticsEvaluationReportsCreateBodyMaxSampleSizeMax = 2147483647

export const llmAnalyticsEvaluationReportsCreateBodyTriggerThresholdMin = 10
export const llmAnalyticsEvaluationReportsCreateBodyTriggerThresholdMax = 10000

export const llmAnalyticsEvaluationReportsCreateBodyCooldownMinutesMin = 60
export const llmAnalyticsEvaluationReportsCreateBodyCooldownMinutesMax = 1440

export const llmAnalyticsEvaluationReportsCreateBodyDailyRunCapMax = 24

export const LlmAnalyticsEvaluationReportsCreateBody = /* @__PURE__ */ zod.object({
    evaluation: zod.string().describe('UUID of the evaluation this report config belongs to.'),
    frequency: zod
        .enum(['scheduled', 'every_n'])
        .describe('* `scheduled` - Scheduled\n* `every_n` - Every N')
        .optional()
        .describe(
            "How report generation is triggered. 'every_n' fires once N new evaluation results have accumulated (subject to cooldown_minutes and daily_run_cap). 'scheduled' fires on the cadence defined by rrule + starts_at + timezone_name.\n\n* `scheduled` - Scheduled\n* `every_n` - Every N"
        ),
    rrule: zod
        .string()
        .optional()
        .describe(
            "RFC 5545 recurrence rule string (e.g. 'FREQ=WEEKLY;BYDAY=MO'). Must not contain DTSTART — the anchor is set via starts_at. Required when frequency is 'scheduled'; ignored otherwise."
        ),
    starts_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            "Anchor datetime for the rrule (ISO 8601, UTC — must end in 'Z'). Local-time interpretation is controlled by timezone_name. Required when frequency is 'scheduled'; ignored otherwise."
        ),
    timezone_name: zod
        .string()
        .max(llmAnalyticsEvaluationReportsCreateBodyTimezoneNameMax)
        .optional()
        .describe(
            "IANA timezone name used to expand the rrule in local time so e.g. '9am' stays at 9am across DST transitions (e.g. 'America/New_York'). Defaults to 'UTC'."
        ),
    delivery_targets: zod
        .unknown()
        .optional()
        .describe(
            "List of delivery targets. Each entry is either {type: 'email', value: 'user@example.com'} or {type: 'slack', integration_id: <int>, channel: '<channel>'}. Slack integration_id must belong to this team."
        ),
    max_sample_size: zod
        .number()
        .min(llmAnalyticsEvaluationReportsCreateBodyMaxSampleSizeMin)
        .max(llmAnalyticsEvaluationReportsCreateBodyMaxSampleSizeMax)
        .optional()
        .describe('Maximum number of evaluation runs included in each report. Defaults to 200.'),
    enabled: zod.boolean().optional().describe('Whether report delivery is active. Disabled configs do not fire.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete this report config.'),
    report_prompt_guidance: zod
        .string()
        .optional()
        .describe(
            'Optional custom instructions appended to the AI report prompt to steer focus, scope, or section choices without modifying the base prompt.'
        ),
    trigger_threshold: zod
        .number()
        .min(llmAnalyticsEvaluationReportsCreateBodyTriggerThresholdMin)
        .max(llmAnalyticsEvaluationReportsCreateBodyTriggerThresholdMax)
        .nullish()
        .describe(
            "Number of new evaluation results that triggers a report (every_n mode only). Min 10, max 10000. Defaults to 100. Required when frequency is 'every_n'."
        ),
    cooldown_minutes: zod
        .number()
        .min(llmAnalyticsEvaluationReportsCreateBodyCooldownMinutesMin)
        .max(llmAnalyticsEvaluationReportsCreateBodyCooldownMinutesMax)
        .optional()
        .describe(
            'Minimum minutes between count-triggered reports to prevent spam (every_n mode only). Min 60, max 1440 (24 hours). Defaults to 60.'
        ),
    daily_run_cap: zod
        .number()
        .min(1)
        .max(llmAnalyticsEvaluationReportsCreateBodyDailyRunCapMax)
        .optional()
        .describe(
            'Maximum count-triggered report runs per calendar day (UTC). Min 1, max 24 (one per cooldown window). Defaults to 10.'
        ),
})

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const LlmAnalyticsEvaluationReportsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * CRUD for evaluation report configurations + report run history.
 */
export const LlmAnalyticsEvaluationReportsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsEvaluationReportsPartialUpdateBodyTimezoneNameMax = 64

export const llmAnalyticsEvaluationReportsPartialUpdateBodyMaxSampleSizeMin = -2147483648
export const llmAnalyticsEvaluationReportsPartialUpdateBodyMaxSampleSizeMax = 2147483647

export const llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMin = 10
export const llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMax = 10000

export const llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMin = 60
export const llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMax = 1440

export const llmAnalyticsEvaluationReportsPartialUpdateBodyDailyRunCapMax = 24

export const LlmAnalyticsEvaluationReportsPartialUpdateBody = /* @__PURE__ */ zod.object({
    evaluation: zod.string().optional().describe('UUID of the evaluation this report config belongs to.'),
    frequency: zod
        .enum(['scheduled', 'every_n'])
        .describe('* `scheduled` - Scheduled\n* `every_n` - Every N')
        .optional()
        .describe(
            "How report generation is triggered. 'every_n' fires once N new evaluation results have accumulated (subject to cooldown_minutes and daily_run_cap). 'scheduled' fires on the cadence defined by rrule + starts_at + timezone_name.\n\n* `scheduled` - Scheduled\n* `every_n` - Every N"
        ),
    rrule: zod
        .string()
        .optional()
        .describe(
            "RFC 5545 recurrence rule string (e.g. 'FREQ=WEEKLY;BYDAY=MO'). Must not contain DTSTART — the anchor is set via starts_at. Required when frequency is 'scheduled'; ignored otherwise."
        ),
    starts_at: zod.iso
        .datetime({ offset: true })
        .nullish()
        .describe(
            "Anchor datetime for the rrule (ISO 8601, UTC — must end in 'Z'). Local-time interpretation is controlled by timezone_name. Required when frequency is 'scheduled'; ignored otherwise."
        ),
    timezone_name: zod
        .string()
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyTimezoneNameMax)
        .optional()
        .describe(
            "IANA timezone name used to expand the rrule in local time so e.g. '9am' stays at 9am across DST transitions (e.g. 'America/New_York'). Defaults to 'UTC'."
        ),
    delivery_targets: zod
        .unknown()
        .optional()
        .describe(
            "List of delivery targets. Each entry is either {type: 'email', value: 'user@example.com'} or {type: 'slack', integration_id: <int>, channel: '<channel>'}. Slack integration_id must belong to this team."
        ),
    max_sample_size: zod
        .number()
        .min(llmAnalyticsEvaluationReportsPartialUpdateBodyMaxSampleSizeMin)
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyMaxSampleSizeMax)
        .optional()
        .describe('Maximum number of evaluation runs included in each report. Defaults to 200.'),
    enabled: zod.boolean().optional().describe('Whether report delivery is active. Disabled configs do not fire.'),
    deleted: zod.boolean().optional().describe('Set to true to soft-delete this report config.'),
    report_prompt_guidance: zod
        .string()
        .optional()
        .describe(
            'Optional custom instructions appended to the AI report prompt to steer focus, scope, or section choices without modifying the base prompt.'
        ),
    trigger_threshold: zod
        .number()
        .min(llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMin)
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMax)
        .nullish()
        .describe(
            "Number of new evaluation results that triggers a report (every_n mode only). Min 10, max 10000. Defaults to 100. Required when frequency is 'every_n'."
        ),
    cooldown_minutes: zod
        .number()
        .min(llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMin)
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMax)
        .optional()
        .describe(
            'Minimum minutes between count-triggered reports to prevent spam (every_n mode only). Min 60, max 1440 (24 hours). Defaults to 60.'
        ),
    daily_run_cap: zod
        .number()
        .min(1)
        .max(llmAnalyticsEvaluationReportsPartialUpdateBodyDailyRunCapMax)
        .optional()
        .describe(
            'Maximum count-triggered report runs per calendar day (UTC). Min 1, max 24 (one per cooldown window). Defaults to 10.'
        ),
})

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const LlmAnalyticsEvaluationReportsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Trigger immediate report generation.
 */
export const LlmAnalyticsEvaluationReportsGenerateCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * List report runs (history) for this report.
 */
export const LlmAnalyticsEvaluationReportsRunsListParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this evaluation report.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsEvaluationReportsRunsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 *
 * Generate an AI-powered summary of evaluation results.
 *
 * This endpoint analyzes evaluation runs and identifies patterns in passing
 * and failing evaluations, providing actionable recommendations.
 *
 * Data is fetched server-side by evaluation ID to ensure data integrity.
 *
 * **Use Cases:**
 * - Understand why evaluations are passing or failing
 * - Identify systematic issues in LLM responses
 * - Get recommendations for improving response quality
 * - Review patterns across many evaluation runs at once
 *
 */
export const LlmAnalyticsEvaluationSummaryCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsEvaluationSummaryCreateBodyFilterDefault = `all`
export const llmAnalyticsEvaluationSummaryCreateBodyGenerationIdsMax = 250

export const llmAnalyticsEvaluationSummaryCreateBodyForceRefreshDefault = false

export const LlmAnalyticsEvaluationSummaryCreateBody = /* @__PURE__ */ zod
    .object({
        evaluation_id: zod.string().describe('UUID of the evaluation config to summarize'),
        filter: zod
            .enum(['all', 'pass', 'fail', 'na'])
            .describe('* `all` - all\n* `pass` - pass\n* `fail` - fail\n* `na` - na')
            .default(llmAnalyticsEvaluationSummaryCreateBodyFilterDefault)
            .describe(
                "Filter type to apply ('all', 'pass', 'fail', or 'na')\n\n* `all` - all\n* `pass` - pass\n* `fail` - fail\n* `na` - na"
            ),
        generation_ids: zod
            .array(zod.string())
            .max(llmAnalyticsEvaluationSummaryCreateBodyGenerationIdsMax)
            .optional()
            .describe('Optional: specific generation IDs to include in summary (max 250)'),
        force_refresh: zod
            .boolean()
            .default(llmAnalyticsEvaluationSummaryCreateBodyForceRefreshDefault)
            .describe('If true, bypass cache and generate a fresh summary'),
    })
    .describe('Request serializer for evaluation summary - accepts IDs only, fetches data server-side.')

/**
 * List available models for a provider.
 */
export const LlmAnalyticsModelsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsModelsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    key_id: zod
        .string()
        .optional()
        .describe(
            'Optional provider key UUID. When supplied, models reachable with that specific key are returned (useful for Azure OpenAI, where the deployment list depends on the configured endpoint). Must belong to the same provider as the `provider` parameter.'
        ),
    provider: zod
        .enum([
            'anthropic',
            'azure_openai',
            'fireworks',
            'gemini',
            'minimax',
            'openai',
            'openrouter',
            'together_ai',
            'zeabur',
        ])
        .describe('LLM provider to list models for. Must be one of the supported providers.'),
})

export const LlmAnalyticsProviderKeysListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsProviderKeysListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

export const LlmAnalyticsProviderKeysRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this llm provider key.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsReviewQueueItemsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsReviewQueueItemsListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod.string().optional().describe('Order by `created_at` or `updated_at`.'),
    queue_id: zod.string().optional().describe('Filter by a specific review queue ID.'),
    search: zod.string().optional().describe('Search pending trace IDs.'),
    trace_id: zod.string().optional().describe('Filter by an exact trace ID.'),
    trace_id__in: zod.string().optional().describe('Filter by multiple trace IDs separated by commas.'),
})

export const LlmAnalyticsReviewQueueItemsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsReviewQueueItemsCreateBodyTraceIdMax = 255

export const LlmAnalyticsReviewQueueItemsCreateBody = /* @__PURE__ */ zod.object({
    queue_id: zod.string().describe('Review queue ID that should own this pending trace.'),
    trace_id: zod
        .string()
        .max(llmAnalyticsReviewQueueItemsCreateBodyTraceIdMax)
        .describe('Trace ID to add to the selected review queue.'),
})

export const LlmAnalyticsReviewQueueItemsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this review queue item.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsReviewQueueItemsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this review queue item.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsReviewQueueItemsPartialUpdateBody = /* @__PURE__ */ zod.object({
    queue_id: zod.string().optional().describe('Review queue ID that should own this pending trace.'),
})

export const LlmAnalyticsReviewQueueItemsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this review queue item.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsReviewQueuesListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsReviewQueuesListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    name: zod.string().optional(),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod.string().optional().describe('Order by `name`, `updated_at`, or `created_at`.'),
    search: zod.string().optional().describe('Search review queue names.'),
})

export const LlmAnalyticsReviewQueuesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsReviewQueuesCreateBodyNameMax = 255

export const LlmAnalyticsReviewQueuesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(llmAnalyticsReviewQueuesCreateBodyNameMax).describe('Human-readable queue name.'),
})

export const LlmAnalyticsReviewQueuesRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this review queue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsReviewQueuesPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this review queue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsReviewQueuesPartialUpdateBodyNameMax = 255

export const LlmAnalyticsReviewQueuesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod
        .string()
        .max(llmAnalyticsReviewQueuesPartialUpdateBodyNameMax)
        .optional()
        .describe('Human-readable queue name.'),
})

export const LlmAnalyticsReviewQueuesDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this review queue.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsScoreDefinitionsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsScoreDefinitionsListQueryParams = /* @__PURE__ */ zod.object({
    archived: zod.boolean().optional().describe('Filter by archived state.'),
    kind: zod.string().optional().describe('Filter by scorer kind.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod.string().optional().describe('Sort by name, kind, created_at, updated_at, or current_version.'),
    search: zod.string().optional().describe('Search scorers by name or description.'),
})

export const LlmAnalyticsScoreDefinitionsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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

export const LlmAnalyticsScoreDefinitionsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this score definition.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsScoreDefinitionsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this score definition.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
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

export const LlmAnalyticsScoreDefinitionsNewVersionCreateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this score definition.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
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
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            "Version number the caller observed before requesting this bump. If provided and it does not match the scorer's current version, the request fails with 409. Omit to skip the optimistic-concurrency check."
        ),
})

/**
 *
 * Generate an AI-powered summary of an LLM trace or event.
 *
 * This endpoint analyzes the provided trace/event, generates a line-numbered text
 * representation, and uses an LLM to create a concise summary with line references.
 *
 * **Two ways to use this endpoint:**
 *
 * 1. **By ID (recommended):** Pass `trace_id` or `generation_id` with an optional `date_from`/`date_to`.
 *    The backend fetches the data automatically. `summarize_type` is inferred.
 * 2. **By data:** Pass the full trace/event data blob in `data` with `summarize_type`.
 *    This is how the frontend uses it.
 *
 * **Summary Format:**
 * - Title (concise, max 10 words)
 * - Mermaid flow diagram showing the main flow
 * - 3-10 summary bullets with line references
 * - "Interesting Notes" section for failures, successes, or unusual patterns
 * - Line references in [L45] or [L45-52] format pointing to relevant sections
 *
 * The response includes the structured summary, the text representation, and metadata.
 *
 */
export const LlmAnalyticsSummarizationCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

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

export const LlmAnalyticsTraceReviewsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsTraceReviewsListQueryParams = /* @__PURE__ */ zod.object({
    definition_id: zod.string().optional().describe('Filter by a stable scorer definition ID.'),
    definition_id__in: zod
        .string()
        .optional()
        .describe('Filter by multiple scorer definition IDs separated by commas.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod.string().optional().describe('Order by `updated_at` or `created_at`.'),
    search: zod.string().optional().describe('Search trace IDs and comments.'),
    trace_id: zod.string().optional().describe('Filter by an exact trace ID.'),
    trace_id__in: zod.string().optional().describe('Filter by multiple trace IDs separated by commas.'),
})

export const LlmAnalyticsTraceReviewsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
    comment: zod.string().nullish().describe('Optional comment or reasoning for the review.'),
    scores: zod
        .array(
            zod.object({
                definition_id: zod.string().describe('Stable scorer definition ID.'),
                definition_version_id: zod
                    .string()
                    .nullish()
                    .describe("Optional immutable scorer version ID. Defaults to the scorer's current version."),
                categorical_values: zod
                    .array(zod.string().max(llmAnalyticsTraceReviewsCreateBodyScoresItemCategoricalValuesItemMax))
                    .min(1)
                    .nullish()
                    .describe('Categorical option keys selected for this score.'),
                numeric_value: zod
                    .stringFormat('decimal', llmAnalyticsTraceReviewsCreateBodyScoresItemNumericValueRegExp)
                    .nullish()
                    .describe('Numeric value selected for this score.'),
                boolean_value: zod.boolean().nullish().describe('Boolean value selected for this score.'),
            })
        )
        .optional()
        .describe('Full desired score set for this review. Omit scorers you want to leave blank.'),
    queue_id: zod
        .string()
        .nullish()
        .describe(
            'Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.'
        ),
})

export const LlmAnalyticsTraceReviewsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this trace review.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmAnalyticsTraceReviewsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this trace review.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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
    comment: zod.string().nullish().describe('Optional comment or reasoning for the review.'),
    scores: zod
        .array(
            zod.object({
                definition_id: zod.string().describe('Stable scorer definition ID.'),
                definition_version_id: zod
                    .string()
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
                    .stringFormat('decimal', llmAnalyticsTraceReviewsPartialUpdateBodyScoresItemNumericValueRegExp)
                    .nullish()
                    .describe('Numeric value selected for this score.'),
                boolean_value: zod.boolean().nullish().describe('Boolean value selected for this score.'),
            })
        )
        .optional()
        .describe('Full desired score set for this review. Omit scorers you want to leave blank.'),
    queue_id: zod
        .string()
        .nullish()
        .describe(
            'Optional review queue ID for queue-context saves. When provided, the matching pending queue item is cleared after the review is saved. If omitted, any pending queue item for the same trace is cleared.'
        ),
})

export const LlmAnalyticsTraceReviewsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.string().describe('A UUID string identifying this trace review.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmPromptsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmPromptsListQueryContentDefault = `full`

export const LlmPromptsListQueryParams = /* @__PURE__ */ zod.object({
    content: zod
        .enum(['full', 'preview', 'none'])
        .default(llmPromptsListQueryContentDefault)
        .describe(
            "Controls how much prompt content is included in the response. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely. The outline field is always included.\n\n* `full` - full\n* `preview` - preview\n* `none` - none"
        ),
    created_by_id: zod.number().optional().describe('Filter prompts by the ID of the user who created them.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Optional substring filter applied to prompt names and prompt content.'),
})

export const LlmPromptsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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

export const llmPromptsNameRetrievePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNameRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNameRetrievePathPromptNameRegExp),
})

export const llmPromptsNameRetrieveQueryContentDefault = `full`

export const LlmPromptsNameRetrieveQueryParams = /* @__PURE__ */ zod.object({
    content: zod
        .enum(['full', 'preview', 'none'])
        .default(llmPromptsNameRetrieveQueryContentDefault)
        .describe(
            "Controls how much prompt content is included in the response. 'full' includes the full prompt, 'preview' includes a short prompt_preview, and 'none' omits prompt content entirely. The outline field is always included.\n\n* `full` - full\n* `preview` - preview\n* `none` - none"
        ),
    version: zod
        .number()
        .min(1)
        .optional()
        .describe('Specific prompt version to fetch. If omitted, the latest version is returned.'),
})

export const llmPromptsNamePartialUpdatePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNamePartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNamePartialUpdatePathPromptNameRegExp),
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

export const llmPromptsNameDuplicateCreatePathPromptNameRegExp = new RegExp('^[^/]+$')

export const LlmPromptsNameDuplicateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    prompt_name: zod.string().regex(llmPromptsNameDuplicateCreatePathPromptNameRegExp),
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

export const TaggersListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const TaggersListQueryParams = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional().describe('Filter by enabled status'),
    id__in: zod.array(zod.string()).optional().describe('Multiple values may be separated by commas.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order_by: zod
        .array(zod.string())
        .optional()
        .describe(
            'Ordering\n\n* `created_at` - Created At\n* `-created_at` - Created At (descending)\n* `updated_at` - Updated At\n* `-updated_at` - Updated At (descending)\n* `name` - Name\n* `-name` - Name (descending)'
        ),
    search: zod.string().optional().describe('Search in name or description'),
})

export const TaggersCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const taggersCreateBodyNameMax = 400

export const taggersCreateBodyTaggerTypeDefault = `llm`
export const taggersCreateBodyTaggerConfigOneOneTagsItemNameMax = 100

export const taggersCreateBodyTaggerConfigOneOneTagsItemDescriptionDefault = ``
export const taggersCreateBodyTaggerConfigOneOneTagsItemDescriptionMax = 500

export const taggersCreateBodyTaggerConfigOneOneMinTagsDefault = 0
export const taggersCreateBodyTaggerConfigOneOneMinTagsMin = 0

export const taggersCreateBodyTaggerConfigOneTwoTagsItemNameMax = 100

export const taggersCreateBodyTaggerConfigOneTwoTagsItemDescriptionDefault = ``
export const taggersCreateBodyTaggerConfigOneTwoTagsItemDescriptionMax = 500

export const taggersCreateBodyConditionsItemIdMax = 100

export const taggersCreateBodyConditionsItemRolloutPercentageDefault = 100
export const taggersCreateBodyConditionsItemRolloutPercentageMin = 0
export const taggersCreateBodyConditionsItemRolloutPercentageMax = 100

export const taggersCreateBodyModelConfigurationOneModelMax = 100

export const TaggersCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(taggersCreateBodyNameMax),
    description: zod.string().optional(),
    enabled: zod.boolean().optional(),
    tagger_type: zod
        .enum(['llm', 'hog'])
        .describe('* `llm` - LLM\n* `hog` - Hog')
        .default(taggersCreateBodyTaggerTypeDefault),
    tagger_config: zod
        .union([
            zod.object({
                prompt: zod.string().min(1).describe('Prompt instructing the LLM how to tag generations'),
                tags: zod
                    .array(
                        zod.object({
                            name: zod
                                .string()
                                .max(taggersCreateBodyTaggerConfigOneOneTagsItemNameMax)
                                .describe('Tag identifier'),
                            description: zod
                                .string()
                                .max(taggersCreateBodyTaggerConfigOneOneTagsItemDescriptionMax)
                                .default(taggersCreateBodyTaggerConfigOneOneTagsItemDescriptionDefault)
                                .describe('Description to help the LLM classify'),
                        })
                    )
                    .describe('Available tags the LLM can assign'),
                min_tags: zod
                    .number()
                    .min(taggersCreateBodyTaggerConfigOneOneMinTagsMin)
                    .default(taggersCreateBodyTaggerConfigOneOneMinTagsDefault)
                    .describe('Minimum number of tags to apply'),
                max_tags: zod.number().min(1).nullish().describe('Maximum number of tags to apply (null = no limit)'),
            }),
            zod.object({
                source: zod.string().min(1).describe('Hog source code to classify a generation into tags.'),
                tags: zod
                    .array(
                        zod.object({
                            name: zod
                                .string()
                                .max(taggersCreateBodyTaggerConfigOneTwoTagsItemNameMax)
                                .describe('Tag identifier'),
                            description: zod
                                .string()
                                .max(taggersCreateBodyTaggerConfigOneTwoTagsItemDescriptionMax)
                                .default(taggersCreateBodyTaggerConfigOneTwoTagsItemDescriptionDefault)
                                .describe('Description to help the LLM classify'),
                        })
                    )
                    .optional()
                    .describe('Optional tag whitelist. Leave empty to allow any tag returned by the Hog code.'),
            }),
        ])
        .describe(
            "Tagger configuration. For tagger_type 'llm': {prompt, tags, min_tags?, max_tags?}. For tagger_type 'hog': {source, tags?}."
        ),
    conditions: zod
        .array(
            zod.object({
                id: zod
                    .string()
                    .max(taggersCreateBodyConditionsItemIdMax)
                    .describe('Stable identifier for this condition'),
                rollout_percentage: zod
                    .number()
                    .min(taggersCreateBodyConditionsItemRolloutPercentageMin)
                    .max(taggersCreateBodyConditionsItemRolloutPercentageMax)
                    .default(taggersCreateBodyConditionsItemRolloutPercentageDefault)
                    .describe('Percentage of matching events to apply this condition to'),
                properties: zod
                    .array(zod.record(zod.string(), zod.unknown()))
                    .optional()
                    .describe('Property filters that scope when this condition fires'),
            })
        )
        .optional()
        .describe('Conditions that scope when the tagger runs'),
    model_configuration: zod
        .union([
            zod.object({
                provider: zod
                    .enum([
                        'openai',
                        'anthropic',
                        'gemini',
                        'openrouter',
                        'fireworks',
                        'azure_openai',
                        'together_ai',
                        'minimax',
                        'zeabur',
                    ])
                    .describe(
                        '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks\n* `azure_openai` - Azure OpenAI\n* `together_ai` - Together AI\n* `minimax` - MiniMax\n* `zeabur` - Zeabur AI Hub'
                    )
                    .describe(
                        'LLM provider to use for this tagger.\n\n* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks\n* `azure_openai` - Azure OpenAI\n* `together_ai` - Together AI\n* `minimax` - MiniMax\n* `zeabur` - Zeabur AI Hub'
                    ),
                model: zod
                    .string()
                    .max(taggersCreateBodyModelConfigurationOneModelMax)
                    .describe('Provider model identifier to use for this tagger.'),
                provider_key_id: zod
                    .string()
                    .nullish()
                    .describe(
                        'Existing LLM provider key UUID for the current project. Do not invent this value; use a real provider key ID returned by PostHog, or omit/null when no provider key should be pinned.'
                    ),
            }),
            zod.null(),
        ])
        .optional(),
})

/**
 * Test Hog tagger code against sample events without saving.
 */
export const TaggersTestHogCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const taggersTestHogCreateBodySampleCountDefault = 5
export const taggersTestHogCreateBodySampleCountMax = 10

export const taggersTestHogCreateBodyTagsItemNameMax = 100

export const taggersTestHogCreateBodyTagsItemDescriptionDefault = ``
export const taggersTestHogCreateBodyTagsItemDescriptionMax = 500

export const TaggersTestHogCreateBody = /* @__PURE__ */ zod.object({
    source: zod
        .string()
        .min(1)
        .describe('Hog source code to test. Return a tag name string, a list of tag name strings, or null.'),
    sample_count: zod
        .number()
        .min(1)
        .max(taggersTestHogCreateBodySampleCountMax)
        .default(taggersTestHogCreateBodySampleCountDefault)
        .describe('Number of recent $ai_generation events to test against (1-10, default 5).'),
    tags: zod
        .array(
            zod.object({
                name: zod
                    .string()
                    .max(taggersTestHogCreateBodyTagsItemNameMax)
                    .describe('Tag identifier to allow in Hog test results.'),
                description: zod
                    .string()
                    .max(taggersTestHogCreateBodyTagsItemDescriptionMax)
                    .default(taggersTestHogCreateBodyTagsItemDescriptionDefault)
                    .describe('Optional description for the tag.'),
            })
        )
        .optional()
        .describe('Optional tag whitelist. Returned tags outside this list are filtered out.'),
})
