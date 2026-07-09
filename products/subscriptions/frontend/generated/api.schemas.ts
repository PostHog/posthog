/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `insight` - Insight
 * * `dashboard` - Dashboard
 * * `ai_prompt` - AI prompt
 */
export type ResourceTypeEnumApi = (typeof ResourceTypeEnumApi)[keyof typeof ResourceTypeEnumApi]

export const ResourceTypeEnumApi = {
    Insight: 'insight',
    Dashboard: 'dashboard',
    AiPrompt: 'ai_prompt',
} as const

/**
 * * `since_last_sent` - Since last report
 * * `last_n_days` - Last N days
 * * `days_ago_range` - Between X and Y days ago
 */
export type AIWindowConfigModeEnumApi = (typeof AIWindowConfigModeEnumApi)[keyof typeof AIWindowConfigModeEnumApi]

export const AIWindowConfigModeEnumApi = {
    SinceLastSent: 'since_last_sent',
    LastNDays: 'last_n_days',
    DaysAgoRange: 'days_ago_range',
} as const

export interface AIWindowConfigApi {
    /** What the report analyzes each run:
     * * `since_last_sent` (default) — everything since the previous successful scheduled delivery (gap-free; test/manual sends don't move the anchor)
     * * `last_n_days` — a fixed trailing window of start_days_ago days
     * * `days_ago_range` — the explicit range from start_days_ago to end_days_ago days ago
     *
     * * `since_last_sent` - Since last report
     * * `last_n_days` - Last N days
     * * `days_ago_range` - Between X and Y days ago */
    mode?: AIWindowConfigModeEnumApi
    /**
     * Lower bound of the analysis window, in days before the run. Required for 'last_n_days' (the N) and 'days_ago_range'; ignored for 'since_last_sent'. 1-365.
     * @minimum 1
     * @maximum 365
     * @nullable
     */
    start_days_ago?: number | null
    /**
     * Upper bound of the analysis window, in days before the run (0 = now). Required for 'days_ago_range' and must be less than start_days_ago; ignored for other modes. 0-365.
     * @minimum 0
     * @maximum 365
     * @nullable
     */
    end_days_ago?: number | null
}

export interface AIPromptConfigApi {
    /** Analysis window for the report. Omitted = 'since_last_sent' (everything since the previous scheduled delivery). */
    window?: AIWindowConfigApi
}

/**
 * * `email` - Email
 * * `slack` - Slack
 */
export type TargetTypeEnumApi = (typeof TargetTypeEnumApi)[keyof typeof TargetTypeEnumApi]

export const TargetTypeEnumApi = {
    Email: 'email',
    Slack: 'slack',
} as const

/**
 * * `daily` - Daily
 * * `weekly` - Weekly
 * * `monthly` - Monthly
 * * `yearly` - Yearly
 */
export type RecurrenceIntervalEnumApi = (typeof RecurrenceIntervalEnumApi)[keyof typeof RecurrenceIntervalEnumApi]

export const RecurrenceIntervalEnumApi = {
    Daily: 'daily',
    Weekly: 'weekly',
    Monthly: 'monthly',
    Yearly: 'yearly',
} as const

/**
 * * `monday` - Monday
 * * `tuesday` - Tuesday
 * * `wednesday` - Wednesday
 * * `thursday` - Thursday
 * * `friday` - Friday
 * * `saturday` - Saturday
 * * `sunday` - Sunday
 */
export type SubscriptionApiByweekdayItem =
    (typeof SubscriptionApiByweekdayItem)[keyof typeof SubscriptionApiByweekdayItem]

export const SubscriptionApiByweekdayItem = {
    Monday: 'monday',
    Tuesday: 'tuesday',
    Wednesday: 'wednesday',
    Thursday: 'thursday',
    Friday: 'friday',
    Saturday: 'saturday',
    Sunday: 'sunday',
} as const

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * Standard Subscription serializer.
 */
export interface SubscriptionApi {
    readonly id: number
    /** What the subscription delivers: 'insight' (snapshot of one insight), 'dashboard' (snapshot of one dashboard), or 'ai_prompt' (LLM-generated report). Read-only — derived from the populated target (insight → insight, dashboard → dashboard, prompt → ai_prompt).
     *
     * * `insight` - Insight
     * * `dashboard` - Dashboard
     * * `ai_prompt` - AI prompt */
    readonly resource_type: ResourceTypeEnumApi
    /**
     * Dashboard ID to subscribe to (mutually exclusive with insight on create).
     * @nullable
     */
    dashboard?: number | null
    /**
     * Insight ID to subscribe to (mutually exclusive with dashboard on create).
     * @nullable
     */
    insight?: number | null
    /** @nullable */
    readonly insight_short_id: string | null
    /** @nullable */
    readonly resource_name: string | null
    /** List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6. */
    dashboard_export_insights?: number[]
    /**
     * Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters.
     * @nullable
     */
    prompt?: string | null
    /** Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes. */
    ai_prompt_config?: AIPromptConfigApi
    /** Delivery channel: email or slack.
     *
     * * `email` - Email
     * * `slack` - Slack */
    target_type: TargetTypeEnumApi
    /** Recipient(s): comma-separated email addresses for email, or Slack channel name/ID for slack. */
    target_value: string
    /** How often to deliver: daily, weekly, monthly, or yearly.
     *
     * * `daily` - Daily
     * * `weekly` - Weekly
     * * `monthly` - Monthly
     * * `yearly` - Yearly */
    frequency: RecurrenceIntervalEnumApi
    /**
     * Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Required on create; must be 1 or greater.
     * @minimum 1
     * @maximum 2147483647
     */
    interval: number
    /**
     * Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.
     * @nullable
     */
    byweekday?: SubscriptionApiByweekdayItem[] | null
    /**
     * Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    bysetpos?: number | null
    /**
     * Total number of deliveries before the subscription stops. Null for unlimited.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    count?: number | null
    /** When to start delivering (ISO 8601 datetime). */
    start_date: string
    /**
     * When to stop delivering (ISO 8601 datetime). Null for indefinite.
     * @nullable
     */
    until_date?: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** Set to true to soft-delete. Subscriptions cannot be hard-deleted. */
    deleted?: boolean
    /** Whether the subscription is active. Set to false to pause delivery without deleting. Auto-set to false when the delivery integration becomes invalid. */
    enabled?: boolean
    /**
     * Human-readable name for this subscription.
     * @maxLength 100
     * @nullable
     */
    title?: string | null
    /** Human-readable schedule summary, e.g. 'sent daily'. */
    readonly summary: string
    /** @nullable */
    readonly next_delivery_date: string | null
    /**
     * ID of a connected Slack integration. Required when target_type is slack.
     * @nullable
     */
    integration_id?: number | null
    /**
     * Optional message included in the invitation email when adding new recipients.
     * @nullable
     */
    invite_message?: string | null
    /** Whether to immediately deliver the subscription once on save so the editor can confirm it looks right. Defaults to true on create and false on update. The recurring schedule is unaffected. */
    send_test_now?: boolean
    /** Whether to attach an AI-generated summary to each delivery (insight and dashboard subscriptions only). Requires the organization to have approved AI data processing, and is subject to the org's active-summary cap and AI credit budget; otherwise the write is rejected. Not applicable to prompt subscriptions, which are themselves AI-generated. */
    summary_enabled?: boolean
    /**
     * Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics to emphasize. Only settable when AI summary context is enabled for the organization; clearing it (empty string) is always allowed.
     * @maxLength 500
     */
    summary_prompt_guide?: string
}

export interface PaginatedSubscriptionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SubscriptionApi[]
}

/**
 * * `monday` - Monday
 * * `tuesday` - Tuesday
 * * `wednesday` - Wednesday
 * * `thursday` - Thursday
 * * `friday` - Friday
 * * `saturday` - Saturday
 * * `sunday` - Sunday
 */
export type PatchedSubscriptionApiByweekdayItem =
    (typeof PatchedSubscriptionApiByweekdayItem)[keyof typeof PatchedSubscriptionApiByweekdayItem]

export const PatchedSubscriptionApiByweekdayItem = {
    Monday: 'monday',
    Tuesday: 'tuesday',
    Wednesday: 'wednesday',
    Thursday: 'thursday',
    Friday: 'friday',
    Saturday: 'saturday',
    Sunday: 'sunday',
} as const

/**
 * Standard Subscription serializer.
 */
export interface PatchedSubscriptionApi {
    readonly id?: number
    /** What the subscription delivers: 'insight' (snapshot of one insight), 'dashboard' (snapshot of one dashboard), or 'ai_prompt' (LLM-generated report). Read-only — derived from the populated target (insight → insight, dashboard → dashboard, prompt → ai_prompt).
     *
     * * `insight` - Insight
     * * `dashboard` - Dashboard
     * * `ai_prompt` - AI prompt */
    readonly resource_type?: ResourceTypeEnumApi
    /**
     * Dashboard ID to subscribe to (mutually exclusive with insight on create).
     * @nullable
     */
    dashboard?: number | null
    /**
     * Insight ID to subscribe to (mutually exclusive with dashboard on create).
     * @nullable
     */
    insight?: number | null
    /** @nullable */
    readonly insight_short_id?: string | null
    /** @nullable */
    readonly resource_name?: string | null
    /** List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6. */
    dashboard_export_insights?: number[]
    /**
     * Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters.
     * @nullable
     */
    prompt?: string | null
    /** Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes. */
    ai_prompt_config?: AIPromptConfigApi
    /** Delivery channel: email or slack.
     *
     * * `email` - Email
     * * `slack` - Slack */
    target_type?: TargetTypeEnumApi
    /** Recipient(s): comma-separated email addresses for email, or Slack channel name/ID for slack. */
    target_value?: string
    /** How often to deliver: daily, weekly, monthly, or yearly.
     *
     * * `daily` - Daily
     * * `weekly` - Weekly
     * * `monthly` - Monthly
     * * `yearly` - Yearly */
    frequency?: RecurrenceIntervalEnumApi
    /**
     * Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Required on create; must be 1 or greater.
     * @minimum 1
     * @maximum 2147483647
     */
    interval?: number
    /**
     * Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.
     * @nullable
     */
    byweekday?: PatchedSubscriptionApiByweekdayItem[] | null
    /**
     * Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    bysetpos?: number | null
    /**
     * Total number of deliveries before the subscription stops. Null for unlimited.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    count?: number | null
    /** When to start delivering (ISO 8601 datetime). */
    start_date?: string
    /**
     * When to stop delivering (ISO 8601 datetime). Null for indefinite.
     * @nullable
     */
    until_date?: string | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** Set to true to soft-delete. Subscriptions cannot be hard-deleted. */
    deleted?: boolean
    /** Whether the subscription is active. Set to false to pause delivery without deleting. Auto-set to false when the delivery integration becomes invalid. */
    enabled?: boolean
    /**
     * Human-readable name for this subscription.
     * @maxLength 100
     * @nullable
     */
    title?: string | null
    /** Human-readable schedule summary, e.g. 'sent daily'. */
    readonly summary?: string
    /** @nullable */
    readonly next_delivery_date?: string | null
    /**
     * ID of a connected Slack integration. Required when target_type is slack.
     * @nullable
     */
    integration_id?: number | null
    /**
     * Optional message included in the invitation email when adding new recipients.
     * @nullable
     */
    invite_message?: string | null
    /** Whether to immediately deliver the subscription once on save so the editor can confirm it looks right. Defaults to true on create and false on update. The recurring schedule is unaffected. */
    send_test_now?: boolean
    /** Whether to attach an AI-generated summary to each delivery (insight and dashboard subscriptions only). Requires the organization to have approved AI data processing, and is subject to the org's active-summary cap and AI credit budget; otherwise the write is rejected. Not applicable to prompt subscriptions, which are themselves AI-generated. */
    summary_enabled?: boolean
    /**
     * Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics to emphasize. Only settable when AI summary context is enabled for the organization; clearing it (empty string) is always allowed.
     * @maxLength 500
     */
    summary_prompt_guide?: string
}

/**
 * * `starting` - Starting
 * * `completed` - Completed
 * * `failed` - Failed
 * * `skipped` - Skipped
 */
export type SubscriptionDeliveryStatusEnumApi =
    (typeof SubscriptionDeliveryStatusEnumApi)[keyof typeof SubscriptionDeliveryStatusEnumApi]

export const SubscriptionDeliveryStatusEnumApi = {
    Starting: 'starting',
    Completed: 'completed',
    Failed: 'failed',
    Skipped: 'skipped',
} as const

export interface AIReportQueryDiagnosticApi {
    /** What this query step was meant to compute. */
    description: string
    /** The HogQL the assistant generated for this step. */
    hogql: string
    /** Whether the query ran successfully. */
    ok: boolean
    /**
     * Exception class name when the query failed; null on success.
     * @nullable
     */
    error_type: string | null
    /**
     * Human-readable failure reason, present only for query errors safe to surface to the subscription owner (e.g. an unresolved field name); null on success and for internal errors, which expose error_type only.
     * @nullable
     */
    human_readable_error?: string | null
}

export interface SubscriptionDeliveryApi {
    /** Primary key for this delivery row. */
    readonly id: string
    /** Parent subscription id. */
    readonly subscription: number
    /** Temporal workflow id for this delivery run. */
    readonly temporal_workflow_id: string
    /** Dedupes activity retries for the same logical run. */
    readonly idempotency_key: string
    /** Why the run started (e.g. scheduled, manual, target_change). */
    readonly trigger_type: string
    /**
     * Planned send time when applicable.
     * @nullable
     */
    readonly scheduled_at: string | null
    /** Channel snapshot at send time (email or slack). */
    readonly target_type: string
    /** Destination snapshot at send time (emails, channel id, URL). */
    readonly target_value: string
    /**
     * ExportedAsset ids generated for this send.
     * @items.minimum -2147483648
     * @items.maximum 2147483647
     */
    readonly exported_asset_ids: readonly number[]
    /** Snapshot at send time: dashboard metadata, total_insight_count, and per-exported-insight entries (id, short_id, name, query_hash, cache_key, query_results, optional query_error). */
    readonly content_snapshot: unknown
    /** Per-destination outcomes; items use status success, failed, or partial. */
    readonly recipient_results: unknown
    /** Overall run status: starting, completed, failed, or skipped.
     *
     * * `starting` - Starting
     * * `completed` - Completed
     * * `failed` - Failed
     * * `skipped` - Skipped */
    readonly status: SubscriptionDeliveryStatusEnumApi
    /** Top-level failure payload when status is failed, if any. */
    readonly error: unknown
    /** When the delivery row was created. */
    readonly created_at: string
    /** Last ORM update to this row. */
    readonly last_updated_at: string
    /**
     * When the run finished, if applicable.
     * @nullable
     */
    readonly finished_at: string | null
    /**
     * AI-generated summary included in this delivery, when one was produced.
     * @nullable
     */
    readonly change_summary: string | null
    /**
     * AI-generated report markdown delivered by this run. Null for non-AI deliveries or runs without a persisted report.
     * @nullable
     */
    readonly ai_report: string | null
    /**
     * Per-step query diagnostics (generated HogQL + failure type) for this report. Null for non-AI deliveries or runs without persisted diagnostics.
     * @nullable
     */
    readonly ai_report_diagnostics: readonly AIReportQueryDiagnosticApi[] | null
    /**
     * The subscription's prompt as it was when this report was generated. Null for older deliveries and non-AI deliveries.
     * @nullable
     */
    readonly ai_report_prompt: string | null
}

export interface PaginatedSubscriptionDeliveryListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SubscriptionDeliveryApi[]
}

export type SubscriptionsListParams = {
    /**
     * Filter by creator user UUID.
     */
    created_by?: string
    /**
     * Filter by dashboard ID.
     */
    dashboard?: number
    /**
     * Filter to subscriptions on insights that are tiles of the given dashboard ID.
     */
    dashboard_tiles?: number
    /**
     * Filter by insight ID.
     */
    insight?: number
    /**
     * Filter by a comma-separated list of insight IDs.
     */
    insights?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
    /**
     * Filter by subscription resource: insight, dashboard export, or AI report.
     */
    resource_type?: SubscriptionsListResourceType
    /**
     * A search term.
     */
    search?: string
    /**
     * Filter by delivery channel (email or Slack).
     */
    target_type?: SubscriptionsListTargetType
}

export type SubscriptionsListResourceType =
    (typeof SubscriptionsListResourceType)[keyof typeof SubscriptionsListResourceType]

export const SubscriptionsListResourceType = {
    AiPrompt: 'ai_prompt',
    Dashboard: 'dashboard',
    Insight: 'insight',
} as const

export type SubscriptionsListTargetType = (typeof SubscriptionsListTargetType)[keyof typeof SubscriptionsListTargetType]

export const SubscriptionsListTargetType = {
    Email: 'email',
    Slack: 'slack',
} as const

export type SubscriptionsDeliveriesListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Return only deliveries in this run status (starting, completed, failed, or skipped).
     */
    status?: SubscriptionsDeliveriesListStatus
}

export type SubscriptionsDeliveriesListStatus =
    (typeof SubscriptionsDeliveriesListStatus)[keyof typeof SubscriptionsDeliveriesListStatus]

export const SubscriptionsDeliveriesListStatus = {
    Completed: 'completed',
    Failed: 'failed',
    Skipped: 'skipped',
    Starting: 'starting',
} as const

export type SubscriptionsSummaryQuotaRetrieve200 = {
    active_count: number
    /** @nullable */
    limit: number | null
    at_limit: boolean
}
