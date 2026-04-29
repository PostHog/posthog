/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 7 enabled ops
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
