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
 * Create a new evaluation run.

This endpoint validates the request and enqueues a Temporal workflow
to asynchronously execute the evaluation.
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
        .datetime({})
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
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks', 'azure_openai'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks\n* `azure_openai` - Azure OpenAI'
                ),
            model: zod.string().max(evaluationsCreateBodyModelConfigurationOneModelMax),
            provider_key_id: zod.string().nullish(),
            provider_key_name: zod.string().nullish(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
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
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks', 'azure_openai'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks\n* `azure_openai` - Azure OpenAI'
                ),
            model: zod.string().max(evaluationsPartialUpdateBodyModelConfigurationOneModelMax),
            provider_key_id: zod.string().nullish(),
            provider_key_name: zod.string().nullish(),
        })
        .describe('Nested serializer for model configuration.')
        .nullish(),
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

export const llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMin = -2147483648
export const llmAnalyticsEvaluationReportsPartialUpdateBodyTriggerThresholdMax = 2147483647

export const llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMin = -2147483648
export const llmAnalyticsEvaluationReportsPartialUpdateBodyCooldownMinutesMax = 2147483647

export const llmAnalyticsEvaluationReportsPartialUpdateBodyDailyRunCapMin = -2147483648
export const llmAnalyticsEvaluationReportsPartialUpdateBodyDailyRunCapMax = 2147483647

export const LlmAnalyticsEvaluationReportsPartialUpdateBody = /* @__PURE__ */ zod.object({
    evaluation: zod.string().optional().describe('UUID of the evaluation this report config belongs to.'),
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
