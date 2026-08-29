/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 3 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Endpoint to fetch spend data (proxy to billing service).
 */
export const BillingSpendRetrieveQueryParams = /* @__PURE__ */ zod.object({
    breakdowns: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of breakdown dimensions. Valid values are \"type\" and \"team\", for example [\"type\",\"team\"]. Omit for a single aggregate series.'
        ),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    start_date: zod.string().nullish(),
    team_ids: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of numeric team\/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.'
        ),
    usage_types: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period, logs_retention_30d_mb_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. [\"event_count_in_period\",\"recording_count_in_period\"]. Omit for all types.'
        ),
})

export const BillingUsageRetrieveQueryParams = /* @__PURE__ */ zod.object({
    breakdowns: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of breakdown dimensions. Valid values are \"type\" and \"team\", for example [\"type\",\"team\"]. Omit for a single aggregate series.'
        ),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    start_date: zod.string().nullish(),
    team_ids: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of numeric team\/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.'
        ),
    usage_types: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period, logs_retention_30d_mb_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. [\"event_count_in_period\",\"recording_count_in_period\"]. Omit for all types.'
        ),
})
