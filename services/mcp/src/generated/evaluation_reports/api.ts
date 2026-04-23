/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 5 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

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
