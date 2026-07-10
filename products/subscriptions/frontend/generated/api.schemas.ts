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
 * * `pulse_brief` - Pulse brief
 */
export type ResourceTypeEnumApi = (typeof ResourceTypeEnumApi)[keyof typeof ResourceTypeEnumApi]

export const ResourceTypeEnumApi = {
    Insight: 'insight',
    Dashboard: 'dashboard',
    AiPrompt: 'ai_prompt',
    PulseBrief: 'pulse_brief',
} as const

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
    /** What the subscription delivers: 'insight' (snapshot of one insight), 'dashboard' (snapshot of one dashboard), 'ai_prompt' (LLM-generated report), or 'pulse_brief' (scheduled Pulse product brief). Read-only — derived from the populated target (insight → insight, dashboard → dashboard, prompt → ai_prompt, pulse_brief_config_id → pulse_brief).
     *
     * * `insight` - Insight
     * * `dashboard` - Dashboard
     * * `ai_prompt` - AI prompt
     * * `pulse_brief` - Pulse brief */
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
    /**
     * ID of the Pulse brief config this subscription delivers briefs for. Required when resource_type is 'pulse_brief'; must reference an enabled config in your team.
     * @nullable
     */
    pulse_brief_config_id?: string | null
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
    /** What the subscription delivers: 'insight' (snapshot of one insight), 'dashboard' (snapshot of one dashboard), 'ai_prompt' (LLM-generated report), or 'pulse_brief' (scheduled Pulse product brief). Read-only — derived from the populated target (insight → insight, dashboard → dashboard, prompt → ai_prompt, pulse_brief_config_id → pulse_brief).
     *
     * * `insight` - Insight
     * * `dashboard` - Dashboard
     * * `ai_prompt` - AI prompt
     * * `pulse_brief` - Pulse brief */
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
    /**
     * ID of the Pulse brief config this subscription delivers briefs for. Required when resource_type is 'pulse_brief'; must reference an enabled config in your team.
     * @nullable
     */
    pulse_brief_config_id?: string | null
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
     * Filter by insight ID.
     */
    insight?: number
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
     * Filter by subscription resource: insight, dashboard export, AI report, or Pulse brief.
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
    PulseBrief: 'pulse_brief',
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
