/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 51 enabled ops
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
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks', 'azure_openai', 'together_ai'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks\n* `azure_openai` - Azure OpenAI\n* `together_ai` - Together AI'
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
                .enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks', 'azure_openai', 'together_ai'])
                .describe(
                    '* `openai` - Openai\n* `anthropic` - Anthropic\n* `gemini` - Gemini\n* `openrouter` - Openrouter\n* `fireworks` - Fireworks\n* `azure_openai` - Azure OpenAI\n* `together_ai` - Together AI'
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
 * CRUD for clustering job configurations (max 5 per team).
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
 * CRUD for clustering job configurations (max 5 per team).
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
        .datetime({})
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
        .datetime({})
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
        .enum(['anthropic', 'azure_openai', 'fireworks', 'gemini', 'openai', 'openrouter', 'together_ai'])
        .describe('LLM provider to list models for. Must be one of the supported providers.'),
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

export const LlmAnalyticsSentimentCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const llmAnalyticsSentimentCreateBodyIdsMax = 5

export const llmAnalyticsSentimentCreateBodyAnalysisLevelDefault = `trace`
export const llmAnalyticsSentimentCreateBodyForceRefreshDefault = false

export const LlmAnalyticsSentimentCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.string())
        .min(1)
        .max(llmAnalyticsSentimentCreateBodyIdsMax)
        .describe('Trace IDs (analysis_level=trace) or generation event UUIDs (analysis_level=generation).'),
    analysis_level: zod
        .enum(['trace', 'generation'])
        .describe('* `trace` - trace\n* `generation` - generation')
        .default(llmAnalyticsSentimentCreateBodyAnalysisLevelDefault)
        .describe(
            "Whether the IDs are 'trace' IDs or 'generation' IDs.\n\n* `trace` - trace\n* `generation` - generation"
        ),
    force_refresh: zod
        .boolean()
        .default(llmAnalyticsSentimentCreateBodyForceRefreshDefault)
        .describe('If true, bypass cache and reclassify.'),
    date_from: zod
        .string()
        .nullish()
        .describe("Start of date range for the lookup (e.g. '-7d' or '2026-01-01'). Defaults to -30d."),
    date_to: zod.string().nullish().describe('End of date range for the lookup. Defaults to now.'),
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

export const LlmSkillsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const LlmSkillsListQueryParams = /* @__PURE__ */ zod.object({
    created_by_id: zod.number().optional().describe('Filter skills by the ID of the user who created them.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    search: zod.string().optional().describe('Optional substring filter applied to skill names and descriptions.'),
})

export const LlmSkillsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
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

export const llmSkillsNameRetrievePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNameRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNameRetrievePathSkillNameRegExp),
})

export const LlmSkillsNameRetrieveQueryParams = /* @__PURE__ */ zod.object({
    version: zod
        .number()
        .min(1)
        .optional()
        .describe('Specific skill version to fetch. If omitted, the latest version is returned.'),
})

export const llmSkillsNamePartialUpdatePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNamePartialUpdateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNamePartialUpdatePathSkillNameRegExp),
})

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

export const llmSkillsNameDuplicateCreatePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNameDuplicateCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNameDuplicateCreatePathSkillNameRegExp),
})

export const llmSkillsNameDuplicateCreateBodyNewNameMax = 64

export const LlmSkillsNameDuplicateCreateBody = /* @__PURE__ */ zod.object({
    new_name: zod
        .string()
        .max(llmSkillsNameDuplicateCreateBodyNewNameMax)
        .describe('Name for the duplicated skill. Must be unique.'),
})

export const llmSkillsNameFilesCreatePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNameFilesCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNameFilesCreatePathSkillNameRegExp),
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

export const llmSkillsNameFilesRenameCreatePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNameFilesRenameCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNameFilesRenameCreatePathSkillNameRegExp),
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

export const llmSkillsNameFilesRetrievePathFilePathRegExp = new RegExp('^.+$')
export const llmSkillsNameFilesRetrievePathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNameFilesRetrieveParams = /* @__PURE__ */ zod.object({
    file_path: zod.string().regex(llmSkillsNameFilesRetrievePathFilePathRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNameFilesRetrievePathSkillNameRegExp),
})

export const LlmSkillsNameFilesRetrieveQueryParams = /* @__PURE__ */ zod.object({
    version: zod
        .number()
        .min(1)
        .optional()
        .describe('Specific skill version to fetch. If omitted, the latest version is returned.'),
})

export const llmSkillsNameFilesDestroyPathFilePathRegExp = new RegExp('^.+$')
export const llmSkillsNameFilesDestroyPathSkillNameRegExp = new RegExp('^[^/]+$')

export const LlmSkillsNameFilesDestroyParams = /* @__PURE__ */ zod.object({
    file_path: zod.string().regex(llmSkillsNameFilesDestroyPathFilePathRegExp),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
    skill_name: zod.string().regex(llmSkillsNameFilesDestroyPathSkillNameRegExp),
})

export const LlmSkillsNameFilesDestroyQueryParams = /* @__PURE__ */ zod.object({
    base_version: zod
        .number()
        .min(1)
        .optional()
        .describe(
            'Latest version you are editing from. If provided, the request fails with 409 when another write has landed in the meantime.'
        ),
})
