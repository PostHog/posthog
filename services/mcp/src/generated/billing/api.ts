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
export const billingSpendRetrieveQueryAfterMax = 512

export const billingSpendRetrieveQueryPageSizeMax = 1000

export const billingSpendRetrieveQueryTopProjectsMax = 200

export const BillingSpendRetrieveQueryParams = () => zod.object({
    after: zod
        .string()
        .max(billingSpendRetrieveQueryAfterMax)
        .nullish()
        .describe('The `next` cursor from the previous page. Opaque. Ignored without page_size.'),
    breakdowns: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of breakdown dimensions. Valid values are \"type\" and \"team\", for example [\"type\",\"team\"]. Omit for a single aggregate series.'
        ),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    page_size: zod
        .number()
        .min(1)
        .max(billingSpendRetrieveQueryPageSizeMax)
        .nullish()
        .describe(
            'Return at most this many series, ranked by total, with a `next` cursor for the page after. A caller that pages never approaches the size this endpoint refuses oversized breakdowns at. Requires a project breakdown.'
        ),
    start_date: zod.string().nullish(),
    team_ids: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of numeric team\/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.'
        ),
    top_projects: zod
        .number()
        .min(1)
        .max(billingSpendRetrieveQueryTopProjectsMax)
        .nullish()
        .describe(
            "With a project breakdown, return only this many highest-usage projects and fold the rest into a single 'all other projects' series, so the totals still reconcile. Omit it to get every project."
        ),
    usage_types: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period, logs_retention_30d_mb_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. [\"event_count_in_period\",\"recording_count_in_period\"]. Omit for all types.'
        ),
})

export const billingUsageRetrieveQueryAfterMax = 512

export const billingUsageRetrieveQueryPageSizeMax = 1000

export const billingUsageRetrieveQueryTopProjectsMax = 200

export const BillingUsageRetrieveQueryParams = () => zod.object({
    after: zod
        .string()
        .max(billingUsageRetrieveQueryAfterMax)
        .nullish()
        .describe('The `next` cursor from the previous page. Opaque. Ignored without page_size.'),
    breakdowns: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of breakdown dimensions. Valid values are \"type\" and \"team\", for example [\"type\",\"team\"]. Omit for a single aggregate series.'
        ),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    page_size: zod
        .number()
        .min(1)
        .max(billingUsageRetrieveQueryPageSizeMax)
        .nullish()
        .describe(
            'Return at most this many series, ranked by total, with a `next` cursor for the page after. A caller that pages never approaches the size this endpoint refuses oversized breakdowns at. Requires a project breakdown.'
        ),
    start_date: zod.string().nullish(),
    team_ids: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of numeric team\/project IDs to filter on, for example [1,2]. Omit for all projects available to the caller. Full billing-access callers can read all organization projects; member read-only callers are limited to visible projects and any project scope on their token.'
        ),
    top_projects: zod
        .number()
        .min(1)
        .max(billingUsageRetrieveQueryTopProjectsMax)
        .nullish()
        .describe(
            "With a project breakdown, return only this many highest-usage projects and fold the rest into a single 'all other projects' series, so the totals still reconcile. Omit it to get every project."
        ),
    usage_types: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of usage type identifiers to filter on. Valid values: event_count_in_period, exceptions_captured_in_period, recording_count_in_period, rows_synced_in_period, free_historical_rows_synced_in_period, survey_responses_count_in_period, mobile_recording_count_in_period, billable_feature_flag_requests_count_in_period, enhanced_persons_event_count_in_period, ai_event_count_in_period, cdp_billable_invocations_in_period, rows_exported_in_period, ai_credits_used_in_period, signals_credits_used_in_period, posthog_code_credits_used_in_period, posthog_code_token_credits_used_in_period, sandbox_compute_credits_used_in_period, sandbox_compute_cpu_millicore_seconds_in_period, sandbox_compute_memory_mib_seconds_in_period, workflow_emails_sent_in_period, workflow_billable_invocations_in_period, logs_mb_in_period, logs_retention_30d_mb_in_period, replay_vision_credits_used_in_period, data_pipelines, group_analytics. E.g. [\"event_count_in_period\",\"recording_count_in_period\"]. Omit for all types.'
        ),
})
