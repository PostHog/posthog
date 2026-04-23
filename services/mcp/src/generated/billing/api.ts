/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const BillingListQueryParams = /* @__PURE__ */ zod.object({
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
})

/**
 * Endpoint to fetch spend data (proxy to billing service).
 */
export const BillingSpendRetrieveQueryParams = /* @__PURE__ */ zod.object({
    breakdowns: zod.string().nullish(),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    start_date: zod.string().nullish(),
    team_ids: zod.string().nullish(),
    usage_types: zod
        .string()
        .nullish()
        .describe(
            'Comma-separated usage type identifiers to filter on. Valid values: event_count_in_period, enhanced_persons_event_count_in_period, group_analytics, recording_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, exceptions_captured_in_period, survey_responses_count_in_period, ai_event_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, data_pipelines, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period. E.g. "event_count_in_period,recording_count_in_period". Omit for all types.'
        ),
})

export const BillingUsageRetrieveQueryParams = /* @__PURE__ */ zod.object({
    breakdowns: zod.string().nullish(),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    start_date: zod.string().nullish(),
    team_ids: zod.string().nullish(),
    usage_types: zod
        .string()
        .nullish()
        .describe(
            'Comma-separated usage type identifiers to filter on. Valid values: event_count_in_period, enhanced_persons_event_count_in_period, group_analytics, recording_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, exceptions_captured_in_period, survey_responses_count_in_period, ai_event_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, data_pipelines, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period. E.g. "event_count_in_period,recording_count_in_period". Omit for all types.'
        ),
})
