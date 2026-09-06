/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 11 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the features the organization's plans include
 */
export const BillingFeaturesRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the forecast for the rest of the billing period
 */
export const BillingForecastRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the organization's spend limits
 */
export const BillingLimitsRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary List the organization's products
 */
export const BillingProductsListParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const billingProductsListQueryIncludePlansDefault = false

export const BillingProductsListQueryParams = () => zod.object({
    include_plans: zod
        .boolean()
        .default(billingProductsListQueryIncludePlansDefault)
        .describe('Add the `plans` list to each product and add-on. Most of the payload.'),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get one product
 */
export const BillingProductsRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
    product_key: zod.string().describe("The product's key."),
})

export const billingProductsRetrieveQueryIncludePlansDefault = false

export const BillingProductsRetrieveQueryParams = () => zod.object({
    include_plans: zod
        .boolean()
        .default(billingProductsRetrieveQueryIncludePlansDefault)
        .describe('Add the `plans` list to each product and add-on. Most of the payload.'),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get spend so far this billing period
 */
export const BillingSpendSummaryRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Spend over time
 */
export const BillingSpendTimeseriesRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const billingSpendTimeseriesRetrieveQueryLimitDefault = 100
export const billingSpendTimeseriesRetrieveQueryOffsetDefault = 0

export const BillingSpendTimeseriesRetrieveQueryParams = () => zod.object({
    breakdowns: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of breakdown dimensions. Valid values are \"type\" and \"team\", for example [\"type\",\"team\"]. Omit for a single aggregate series.'
        ),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    limit: zod.number().default(billingSpendTimeseriesRetrieveQueryLimitDefault).describe('Series per page.'),
    offset: zod.number().default(billingSpendTimeseriesRetrieveQueryOffsetDefault).describe('Series to skip.'),
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

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get the organization's subscription
 */
export const BillingSubscriptionRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Get usage so far this billing period
 */
export const BillingUsageSummaryRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

/**
 * Read billing state for an organization: subscription, products, features and usage.
 *
 * The schema attributes every operation here to the billing product. Without that the route
 * puts them under organizations, and the MCP tool scaffold, which matches by product, drops
 * the billing tools that name them.
 * @summary Usage over time
 */
export const BillingUsageTimeseriesRetrieveParams = () => zod.object({
    organization_id: zod
        .string()
        .describe(
            "ID of the organization you're trying to access. To find the ID of the organization, make a call to \/api\/organizations\/."
        ),
})

export const billingUsageTimeseriesRetrieveQueryLimitDefault = 100
export const billingUsageTimeseriesRetrieveQueryOffsetDefault = 0

export const BillingUsageTimeseriesRetrieveQueryParams = () => zod.object({
    breakdowns: zod
        .string()
        .nullish()
        .describe(
            'JSON-encoded array of breakdown dimensions. Valid values are \"type\" and \"team\", for example [\"type\",\"team\"]. Omit for a single aggregate series.'
        ),
    end_date: zod.string().nullish(),
    interval: zod.string().nullish(),
    limit: zod.number().default(billingUsageTimeseriesRetrieveQueryLimitDefault).describe('Series per page.'),
    offset: zod.number().default(billingUsageTimeseriesRetrieveQueryOffsetDefault).describe('Series to skip.'),
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
