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

export interface SubscriptionDashboardContextApi {
    /** Dashboard ID used to open the context dashboard. */
    dashboard_id: number
    /** Current display name of the context dashboard. */
    dashboard_name: string
}

export interface SubscriptionInsightContextApi {
    /** Database ID of the context insight. */
    insight_id: number
    /** Stable insight identifier used to open the context insight. */
    insight_short_id: string
    /** Current display name of the context insight. */
    insight_name: string
}

export type SubscriptionContextApi = SubscriptionDashboardContextApi | SubscriptionInsightContextApi

export interface ProactiveSubscriptionConfigApi {
    /** Whether future AI report deliveries may run proactive follow-up. */
    enabled?: boolean
    /**
     * Exact repository in owner/repository format. Required before draft pull requests are allowed.
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * Exact GitHub integration selected with the repository for draft pull request authorization.
     * @minimum 1
     * @nullable
     */
    repository_integration_id?: number | null
    /** Whether Pulse may create one draft pull request on a future delivery. */
    create_draft_pr?: boolean
    /**
     * Optional eligible reviewed public research subject. Omit to disable public research.
     * @nullable
     */
    public_research_subject_id?: string | null
    /**
     * Server-issued active repository grant for the selected repository. It cannot be chosen by clients.
     * @nullable
     */
    readonly repository_grant_id: string | null
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
 * * `student` - Student
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
    Student: 'student',
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
    /** List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 10. */
    dashboard_export_insights?: number[]
    /**
     * Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters.
     * @nullable
     */
    prompt?: string | null
    /** Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes. */
    ai_prompt_config?: AIPromptConfigApi
    /** Dashboards and insights that ground this AI report. Deleted resources are omitted. */
    readonly contexts: readonly SubscriptionContextApi[]
    /** Standing proactive follow-up configuration for future AI report deliveries. */
    readonly proactive_config: ProactiveSubscriptionConfigApi
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
     * Days of week for daily or weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.
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
    /** Whether to immediately deliver the subscription once on save so the editor can confirm it looks right. Defaults to true on create. When omitted on update, a delivery is sent only if the edit changed what gets delivered (recipient, channel, source) or re-enabled the subscription. The recurring schedule is unaffected. */
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

export type SubscriptionWriteApiContextsItem =
    | {
          /** @minimum 1 */
          dashboard_id: number
      }
    | {
          /** @minimum 1 */
          insight_id: number
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
export type SubscriptionWriteApiByweekdayItem =
    (typeof SubscriptionWriteApiByweekdayItem)[keyof typeof SubscriptionWriteApiByweekdayItem]

export const SubscriptionWriteApiByweekdayItem = {
    Monday: 'monday',
    Tuesday: 'tuesday',
    Wednesday: 'wednesday',
    Thursday: 'thursday',
    Friday: 'friday',
    Saturday: 'saturday',
    Sunday: 'sunday',
} as const

export interface ProactiveSubscriptionConfigWriteApi {
    /** Whether future AI report deliveries may run proactive follow-up. */
    enabled?: boolean
    /**
     * Exact repository in owner/repository format. Required before draft pull requests are allowed.
     * @maxLength 255
     * @nullable
     */
    repository?: string | null
    /**
     * Exact GitHub integration selected with the repository for draft pull request authorization.
     * @minimum 1
     * @nullable
     */
    repository_integration_id?: number | null
    /** Whether Pulse may create one draft pull request on a future delivery. */
    create_draft_pr?: boolean
    /**
     * Optional eligible reviewed public research subject. Omit to disable public research.
     * @nullable
     */
    public_research_subject_id?: string | null
}

/**
 * Standard Subscription serializer.
 */
export interface SubscriptionWriteApi {
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
    /** List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 10. */
    dashboard_export_insights?: number[]
    /**
     * Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters.
     * @nullable
     */
    prompt?: string | null
    /** Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes. */
    ai_prompt_config?: AIPromptConfigApi
    /**
     * Complete dashboard and insight context for an AI report. Omit on PATCH to preserve, pass an empty list to clear, or pass up to 3 items to replace all contexts.
     * @maxItems 3
     */
    contexts?: SubscriptionWriteApiContextsItem[]
    /** Optional standing consent and limits for proactive follow-up on future AI report deliveries. */
    proactive_config?: ProactiveSubscriptionConfigWriteApi
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
     * Days of week for daily or weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.
     * @nullable
     */
    byweekday?: SubscriptionWriteApiByweekdayItem[] | null
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
    /** Whether to immediately deliver the subscription once on save so the editor can confirm it looks right. Defaults to true on create. When omitted on update, a delivery is sent only if the edit changed what gets delivered (recipient, channel, source) or re-enabled the subscription. The recurring schedule is unaffected. */
    send_test_now?: boolean
    /** Whether to attach an AI-generated summary to each delivery (insight and dashboard subscriptions only). Requires the organization to have approved AI data processing, and is subject to the org's active-summary cap and AI credit budget; otherwise the write is rejected. Not applicable to prompt subscriptions, which are themselves AI-generated. */
    summary_enabled?: boolean
    /**
     * Optional free-text guidance (max 500 chars) steering the AI summary, e.g. which metrics to emphasize. Only settable when AI summary context is enabled for the organization; clearing it (empty string) is always allowed.
     * @maxLength 500
     */
    summary_prompt_guide?: string
}

export type PatchedSubscriptionWriteApiContextsItem =
    | {
          /** @minimum 1 */
          dashboard_id: number
      }
    | {
          /** @minimum 1 */
          insight_id: number
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
export type PatchedSubscriptionWriteApiByweekdayItem =
    (typeof PatchedSubscriptionWriteApiByweekdayItem)[keyof typeof PatchedSubscriptionWriteApiByweekdayItem]

export const PatchedSubscriptionWriteApiByweekdayItem = {
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
export interface PatchedSubscriptionWriteApi {
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
    /** List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 10. */
    dashboard_export_insights?: number[]
    /**
     * Free-text prompt that drives the AI-generated report. Required when resource_type is 'ai_prompt'. Max 4000 characters.
     * @nullable
     */
    prompt?: string | null
    /** Configuration for AI report subscriptions (analysis window, future knobs). Only valid when resource_type is 'ai_prompt'. Replaced wholesale on writes. */
    ai_prompt_config?: AIPromptConfigApi
    /**
     * Complete dashboard and insight context for an AI report. Omit on PATCH to preserve, pass an empty list to clear, or pass up to 3 items to replace all contexts.
     * @maxItems 3
     */
    contexts?: PatchedSubscriptionWriteApiContextsItem[]
    /** Optional standing consent and limits for proactive follow-up on future AI report deliveries. */
    proactive_config?: ProactiveSubscriptionConfigWriteApi
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
     * Days of week for daily or weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.
     * @nullable
     */
    byweekday?: PatchedSubscriptionWriteApiByweekdayItem[] | null
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
    /** Whether to immediately deliver the subscription once on save so the editor can confirm it looks right. Defaults to true on create. When omitted on update, a delivery is sent only if the edit changed what gets delivered (recipient, channel, source) or re-enabled the subscription. The recurring schedule is unaffected. */
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

export interface AIReportChartApi {
    /** Id of the rendered PNG export backing this chart. */
    export_asset_id: number
    /** Chart caption, taken from the plan step it illustrates. */
    title: string
    /** Index of the plan step this chart came from. */
    step_index: number
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
    /** Why the run started (e.g. scheduled, manual, subscription update). */
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
     * Charts rendered for this report, in the order they were delivered. Empty when the report had no charts. Null for non-AI deliveries and for deliveries recorded before charts existed.
     * @nullable
     */
    readonly ai_report_charts: readonly AIReportChartApi[] | null
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

/**
 * * `adopted` - adopted
 * * `dismissed` - dismissed
 */
export type OutcomeDecisionEnumApi = (typeof OutcomeDecisionEnumApi)[keyof typeof OutcomeDecisionEnumApi]

export const OutcomeDecisionEnumApi = {
    Adopted: 'adopted',
    Dismissed: 'dismissed',
} as const

export interface OutcomeDecisionApi {
    /** Whether to adopt or dismiss this advice-only recommendation.
     *
     * * `adopted` - adopted
     * * `dismissed` - dismissed */
    decision: OutcomeDecisionEnumApi
}

export interface OutcomeDecisionDTOApi {
    /** Stable outcome plan that records this advice decision. */
    plan_id: string
    /** Stable advice-only recommendation receiving this decision. */
    action_id: string
    /** Current explicit decision: adopted or dismissed.
     *
     * * `adopted` - adopted
     * * `dismissed` - dismissed */
    adoption_status: OutcomeDecisionEnumApi
    /** Current server-owned measurement lifecycle state. */
    readout_status: string
    /**
     * When the recommendation was most recently adopted, if adopted.
     * @nullable
     */
    adopted_at: string | null
    /** When the current explicit decision was recorded. */
    decision_at: string
    /** Server-known identifier of the person who made the decision. */
    decided_by_id: number
    /**
     * Scheduled readout time after adoption, if any.
     * @nullable
     */
    next_readout_at: string | null
}

export interface RepositoryOptionApi {
    /** Exact repository currently authorizable by the requesting user, in owner/repository format. */
    repository: string
    /**
     * Exact active GitHub integration that authorizes this repository binding.
     * @minimum 1
     */
    repository_integration_id: number
}

export interface PublicResearchSubjectOptionApi {
    /** Stable identifier of the reviewed public research subject. */
    id: string
    /** Human-readable name of the reviewed public research subject. */
    display_name: string
    /** Canonical public domain covered by this research subject. */
    canonical_domain: string
}

export interface ProactiveConfigurationOptionsApi {
    /** Whether proactive subscription configuration is enabled for this server. */
    proactive_available: boolean
    /** Whether the server currently allows new draft pull request automation. */
    draft_pr_available: boolean
    /** Repositories that the requesting user can currently authorize for a draft pull request. */
    repositories: RepositoryOptionApi[]
    /** Eligible reviewed public research subjects while public research is enabled. */
    public_research_subjects: PublicResearchSubjectOptionApi[]
}

export interface PulseExperimentVariantApi {
    /**
     * New variant key. It cannot identify an existing feature flag.
     * @maxLength 100
     * @pattern ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$
     */
    key: string
    /**
     * Display name for this variant.
     * @maxLength 400
     */
    name: string
}

/**
 * * `event` - event
 * * `action` - action
 */
export type PulseExperimentMetricRefKindEnumApi =
    (typeof PulseExperimentMetricRefKindEnumApi)[keyof typeof PulseExperimentMetricRefKindEnumApi]

export const PulseExperimentMetricRefKindEnumApi = {
    Event: 'event',
    Action: 'action',
} as const

export interface PulseExperimentMetricRefApi {
    /** Metric reference type. Pulse accepts only an event name or an action ID.
     *
     * * `event` - event
     * * `action` - action */
    kind: PulseExperimentMetricRefKindEnumApi
    /**
     * Existing event name when kind is event.
     * @maxLength 400
     */
    event_name?: string
    /**
     * Existing project action ID when kind is action.
     * @minimum 1
     */
    action_id?: number
}

export interface PulseExperimentDraftApi {
    /**
     * Name for the new inert experiment draft.
     * @maxLength 400
     */
    name: string
    /**
     * Testable hypothesis recorded on the draft.
     * @maxLength 1200
     */
    hypothesis: string
    /**
     * Optional explanation of the proposed change.
     * @maxLength 1200
     */
    description?: string
    /**
     * Plain-language audience or behavior targeted by the draft.
     * @maxLength 600
     */
    target_description: string
    /**
     * Two to five new variants. Rollout percentages are derived server-side.
     * @minItems 2
     * @maxItems 5
     */
    variants: PulseExperimentVariantApi[]
    /** One existing event or action used as the primary metric. */
    primary_metric: PulseExperimentMetricRefApi
    /**
     * Up to nine existing event or action references used as secondary metrics.
     * @maxItems 9
     */
    secondary_metrics?: PulseExperimentMetricRefApi[]
}

/**
 * * `verified` - verified
 */
export type PulseExperimentDraftResponseStatusEnumApi =
    (typeof PulseExperimentDraftResponseStatusEnumApi)[keyof typeof PulseExperimentDraftResponseStatusEnumApi]

export const PulseExperimentDraftResponseStatusEnumApi = {
    Verified: 'verified',
} as const

export interface PulseExperimentDraftResponseApi {
    /** Reserved Pulse artifact that owns this draft. */
    artifact_id: string
    /** Selected Pulse action fulfilled by this draft. */
    action_id: string
    /**
     * Created inert experiment draft.
     * @minimum 1
     */
    experiment_id: number
    /**
     * Created inactive zero-traffic feature flag.
     * @minimum 1
     */
    feature_flag_id: number
    /** Whether the draft was verified and recorded.
     *
     * * `verified` - verified */
    status: PulseExperimentDraftResponseStatusEnumApi
}

export interface ArtifactLinkDTOApi {
    /** Server-owned prepared artifact kind. */
    kind: string
    /** Current server-owned artifact state. */
    status: string
    /**
     * Authoritative verified artifact URL, when safe to expose.
     * @nullable
     */
    external_url: string | null
    /**
     * Verified external lifecycle state, when available.
     * @nullable
     */
    external_state: string | null
    /**
     * Bounded server-owned artifact failure code, if any.
     * @nullable
     */
    failure_code: string | null
    /**
     * Server task that prepared this artifact, if any.
     * @nullable
     */
    task_id: string | null
    /**
     * Execution task-run identifier for this artifact, if any.
     * @nullable
     */
    execution_task_run_id: string | null
    /**
     * Verified experiment identifier for an experiment artifact, if any.
     * @nullable
     */
    experiment_id: number | null
}

export interface EvidenceProvenanceDTOApi {
    tool_name: string
    tool_schema_version: string
    /** @nullable */
    started_at: string | null
    /** @nullable */
    completed_at: string | null
    result_truncated: boolean
    /** @nullable */
    error_class: string | null
}

export interface PublicResearchCitationHistoryDTOApi {
    evidence_id: string
    canonical_url: string
    /** @nullable */
    title: string | null
    retrieved_at: string
}

export interface PublicationGateHistoryDTOApi {
    label: string
    status: string
}

export interface BuildTestGateSummaryDTOApi {
    status: string
    /** @nullable */
    completed_at: string | null
    /** @nullable */
    failure_code: string | null
    gates: PublicationGateHistoryDTOApi[]
}

export interface RunActionHistoryDTOApi {
    /** Safe prepared artifacts for this recommendation. */
    artifacts: ArtifactLinkDTOApi[]
    /** Stable recommendation identifier. */
    id: string
    /** Stable server-generated recommendation key. */
    action_key: string
    /** Recommendation or prepared-action kind. */
    kind: string
    /** Safe recommendation title. */
    title: string
    /** Safe recommendation rationale. */
    rationale: string
    /** Safe expected impact summary. */
    expected_impact: string
    /** Server-ranked recommendation position. */
    rank: number
    /** Whether the server selected this action for implementation. */
    implementation_selected: boolean
    /** Current server-owned action state. */
    status: string
    /**
     * Safe reason this recommendation is timely.
     * @nullable
     */
    why_now: string | null
    /**
     * Bounded recommendation confidence, if available.
     * @nullable
     */
    confidence: string | null
    /** Estimated implementation effort. */
    effort: string
    /**
     * Safe metric name used for the recommendation.
     * @nullable
     */
    metric_name: string | null
    /**
     * Metric unit.
     * @nullable
     */
    metric_unit: string | null
    /**
     * Intended metric direction.
     * @nullable
     */
    metric_direction: string | null
    /**
     * Expected-change interpretation.
     * @nullable
     */
    expected_change_type: string | null
    /**
     * Lower expected change bound.
     * @nullable
     */
    expected_change_lower: string | null
    /**
     * Upper expected change bound.
     * @nullable
     */
    expected_change_upper: string | null
    /**
     * Readout delay in days, if measurable.
     * @nullable
     */
    readout_after_days: number | null
    /**
     * Linked server-owned outcome plan, if any.
     * @nullable
     */
    plan_id: string | null
    /**
     * Outcome-plan baseline value, if any.
     * @nullable
     */
    baseline_value: string | null
    /**
     * Start of the baseline interval, if any.
     * @nullable
     */
    baseline_from: string | null
    /**
     * End of the baseline interval, if any.
     * @nullable
     */
    baseline_to: string | null
    /**
     * Current outcome adoption state, if measurable.
     * @nullable
     */
    adoption_status: string | null
    /**
     * Bounded source of the current adoption state, if any.
     * @nullable
     */
    adoption_source: string | null
    /**
     * Most recent adoption timestamp, if adopted.
     * @nullable
     */
    adopted_at: string | null
    /**
     * Timestamp of the current manual decision, if any.
     * @nullable
     */
    decision_at: string | null
    /**
     * Person who made the current manual decision, if any.
     * @nullable
     */
    decided_by_id: number | null
    /**
     * Current outcome readout lifecycle state, if measurable.
     * @nullable
     */
    readout_status: string | null
    /**
     * Next scheduled outcome readout, if any.
     * @nullable
     */
    next_readout_at: string | null
    /** Safe bounded evidence provenance. */
    evidence: EvidenceProvenanceDTOApi[]
    /** Safe bounded public research citations. */
    citations: PublicResearchCitationHistoryDTOApi[]
    /** Verified build and test gate result, if relevant. */
    build_test_gate: BuildTestGateSummaryDTOApi | null
}

/**
 * * `count` - count
 */
export type MetricUnitEnumApi = (typeof MetricUnitEnumApi)[keyof typeof MetricUnitEnumApi]

export const MetricUnitEnumApi = {
    Count: 'count',
} as const

export interface OutcomeReadoutHistoryDTOApi {
    /** Safe artifacts prepared for the source recommendation. */
    artifacts: ArtifactLinkDTOApi[]
    /** Stable immutable outcome observation identifier. */
    id: string
    /** Outcome plan measured by this readout. */
    plan_id: string
    /** Source recommendation for this readout. */
    action_id: string
    /** Safe source recommendation title. */
    recommendation_title: string
    /** Adapter-owned identity for the count scalar. */
    metric_name: string
    /** Adapter-owned count scalar unit.
     *
     * * `count` - count */
    metric_unit: MetricUnitEnumApi
    /** Server-owned baseline metric value. */
    baseline_value: string
    /** Start of the baseline interval. */
    baseline_from: string
    /** End of the baseline interval. */
    baseline_to: string
    /**
     * Observed metric value, if measurement succeeded.
     * @nullable
     */
    observed_value: string | null
    /**
     * Start of the observed interval, if available.
     * @nullable
     */
    observed_from: string | null
    /**
     * End of the observed interval, if available.
     * @nullable
     */
    observed_to: string | null
    /**
     * Observed absolute change, if available.
     * @nullable
     */
    absolute_delta: string | null
    /**
     * Observed relative change, if available.
     * @nullable
     */
    relative_delta: string | null
    /** Immutable observation state. */
    status: string
    /** Server-owned outcome verdict. */
    verdict: string
    /**
     * Server-derived readout confidence, if available.
     * @nullable
     */
    confidence: string | null
    /**
     * Bounded measurement failure code, if any.
     * @nullable
     */
    failure_code: string | null
}

export interface DeliveryHistoryDTOApi {
    status: string
    /** @nullable */
    failure_code: string | null
    /** @nullable */
    accepted_at: string | null
}

export interface PulseRunHistoryDTOApi {
    /** Bounded safe recommendation history. */
    actions: RunActionHistoryDTOApi[]
    /** Immutable authorized outcome readouts, shown before recommendations. */
    readouts: OutcomeReadoutHistoryDTOApi[]
    /** Stable proactive run identifier. */
    id: string
    /** Subscription that owns this run. */
    subscription_id: number
    /** Delivery that triggered this run. */
    delivery_id: string
    /** Terminal or current Pulse run state. */
    status: string
    /**
     * When the run began, if started.
     * @nullable
     */
    started_at: string | null
    /**
     * When the run finished, if terminal.
     * @nullable
     */
    finished_at: string | null
    /**
     * Analysis task identifier, if any.
     * @nullable
     */
    task_id: string | null
    /**
     * Analysis task-run identifier, if any.
     * @nullable
     */
    analysis_task_run_id: string | null
    /**
     * Execution task-run identifier, if any.
     * @nullable
     */
    execution_task_run_id: string | null
    /**
     * Bounded run failure code, if any.
     * @nullable
     */
    failure_code: string | null
    /**
     * Bounded reason a run was skipped, if any.
     * @nullable
     */
    skip_reason: string | null
    /** Bounded delivery outcomes for this run. */
    deliveries: DeliveryHistoryDTOApi[]
}

/**
 * Server-derived measurement arguments. Only the adapter-owned time window differs from baseline.
 */
export type PulseOutcomeReplayResponseApiComparisonArguments = { [key: string]: unknown }

/**
 * Server-validated value selector for the returned measurement result.
 */
export type PulseOutcomeReplayResponseApiSelector = { [key: string]: string }

export interface PulseOutcomeReplayResponseApi {
    /** Claimed outcome plan this replay instruction is bound to. */
    plan_id: string
    /**
     * Only supported read-only measurement tool the current sandbox may execute.
     * @maxLength 100
     */
    tool_name: string
    /**
     * Schema version that must match the returned measurement tool call.
     * @maxLength 32
     */
    tool_schema_version: string
    /** Server-derived measurement arguments. Only the adapter-owned time window differs from baseline. */
    comparison_arguments: PulseOutcomeReplayResponseApiComparisonArguments
    /** Server-validated value selector for the returned measurement result. */
    selector: PulseOutcomeReplayResponseApiSelector
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

export type SubscriptionsPulseHistoryListParams = {
    /**
     * Subscription whose bounded proactive delivery history to return.
     * @minimum 1
     */
    subscription_id: number
}

export type SubscriptionsSummaryQuotaRetrieve200 = {
    active_count: number
    /** @nullable */
    limit: number | null
    at_limit: boolean
}
