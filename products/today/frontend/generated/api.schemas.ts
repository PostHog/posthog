/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface BriefingSegmentApi {
    /** A run of text in a paragraph. Includes its own spaces. */
    text: string
    /**
     * Key of the item this run links to, or null for plain text.
     * @nullable
     */
    item_key: string | null
    /** True only for the run that names the top item. */
    highlight: boolean
}

/**
 * * `draft` - draft
 * * `open` - open
 * * `closed` - closed
 * * `merged` - merged
 */
export type PullRequestStateEnumApi = (typeof PullRequestStateEnumApi)[keyof typeof PullRequestStateEnumApi]

export const PullRequestStateEnumApi = {
    Draft: 'draft',
    Open: 'open',
    Closed: 'closed',
    Merged: 'merged',
} as const

/**
 * * `affected_users` - affected_users
 * * `affected_sessions` - affected_sessions
 * * `occurrences` - occurrences
 * * `conversion_rate` - conversion_rate
 * * `error_rate` - error_rate
 * * `duration` - duration
 * * `revenue` - revenue
 * * `custom` - custom
 */
export type ReportMetricKindEnumApi = (typeof ReportMetricKindEnumApi)[keyof typeof ReportMetricKindEnumApi]

export const ReportMetricKindEnumApi = {
    AffectedUsers: 'affected_users',
    AffectedSessions: 'affected_sessions',
    Occurrences: 'occurrences',
    ConversionRate: 'conversion_rate',
    ErrorRate: 'error_rate',
    Duration: 'duration',
    Revenue: 'revenue',
    Custom: 'custom',
} as const

/**
 * * `primary` - primary
 * * `supporting` - supporting
 */
export type RoleEnumApi = (typeof RoleEnumApi)[keyof typeof RoleEnumApi]

export const RoleEnumApi = {
    Primary: 'primary',
    Supporting: 'supporting',
} as const

/**
 * * `number` - number
 * * `count` - count
 * * `percentage` - percentage
 * * `percentage_scaled` - percentage_scaled
 * * `duration` - duration
 * * `currency` - currency
 */
export type ValueFormatEnumApi = (typeof ValueFormatEnumApi)[keyof typeof ValueFormatEnumApi]

export const ValueFormatEnumApi = {
    Number: 'number',
    Count: 'count',
    Percentage: 'percentage',
    PercentageScaled: 'percentage_scaled',
    Duration: 'duration',
    Currency: 'currency',
} as const

export interface BriefingItemMetricApi {
    /** Stable slug of the metric within its report. */
    metric_id: string
    /** Short label of what the metric measures. */
    title: string
    /** What the value measures, for example affected_users.
     *
     * * `affected_users` - affected_users
     * * `affected_sessions` - affected_sessions
     * * `occurrences` - occurrences
     * * `conversion_rate` - conversion_rate
     * * `error_rate` - error_rate
     * * `duration` - duration
     * * `revenue` - revenue
     * * `custom` - custom */
    kind: ReportMetricKindEnumApi
    /** `primary` for the report's key observation, otherwise `supporting`.
     *
     * * `primary` - primary
     * * `supporting` - supporting */
    role: RoleEnumApi
    /** The latest saved snapshot of the metric. */
    value: number
    /**
     * Trailing per-bucket values saved with the snapshot, oldest first. Null when none were saved.
     * @nullable
     */
    series: number[] | null
    /** How to format the value, for example count.
     *
     * * `number` - number
     * * `count` - count
     * * `percentage` - percentage
     * * `percentage_scaled` - percentage_scaled
     * * `duration` - duration
     * * `currency` - currency */
    value_format: ValueFormatEnumApi
    /**
     * Optional short suffix or currency code, such as USD.
     * @nullable
     */
    unit: string | null
    /** The metric's live InsightVizNode wrapping one TrendsQuery, as the report stores it. */
    query: unknown
}

export interface BriefingItemChartApi {
    /** Stable slug of the chart within its report. */
    chart_id: string
    /** Short heading of the chart. */
    title: string
    /** The query node the report body draws, as the report stores it. */
    query: unknown
}

export interface BriefingItemReportApi {
    /**
     * The report's priority, P0 to P4, or null if unset.
     * @nullable
     */
    priority: string | null
    /** The report's summary, shortened to a few sentences. */
    summary: string
    /** State of the report's implementation pull request, or null when it has none.
     *
     * * `draft` - draft
     * * `open` - open
     * * `closed` - closed
     * * `merged` - merged */
    pull_request_state: PullRequestStateEnumApi | null
    /**
     * URL of the report's implementation pull request, or null when it has none.
     * @nullable
     */
    pull_request_url: string | null
    /** How many signals the report groups. */
    signal_count: number
    /** When the report last changed. */
    updated_at: string
    /** The report's metrics that have a saved snapshot, in the report's order. */
    metrics: BriefingItemMetricApi[]
    /** The charts in the report body, in the report's order. */
    charts: BriefingItemChartApi[]
}

/**
 * * `report` - REPORT
 * * `dashboard` - DASHBOARD
 * * `other` - OTHER
 */
export type TodayItemGroupEnumApi = (typeof TodayItemGroupEnumApi)[keyof typeof TodayItemGroupEnumApi]

export const TodayItemGroupEnumApi = {
    Report: 'report',
    Dashboard: 'dashboard',
    Other: 'other',
} as const

/**
 * * `self_driving` - SELF_DRIVING
 * * `product_analytics` - PRODUCT_ANALYTICS
 * * `alerts` - ALERTS
 * * `support` - SUPPORT
 * * `error_tracking` - ERROR_TRACKING
 * * `github` - GITHUB
 */
export type TodayItemSourceEnumApi = (typeof TodayItemSourceEnumApi)[keyof typeof TodayItemSourceEnumApi]

export const TodayItemSourceEnumApi = {
    SelfDriving: 'self_driving',
    ProductAnalytics: 'product_analytics',
    Alerts: 'alerts',
    Support: 'support',
    ErrorTracking: 'error_tracking',
    Github: 'github',
} as const

/**
 * * `claimed_by_you` - CLAIMED_BY_YOU
 * * `waiting_for_you` - WAITING_FOR_YOU
 * * `suggested_reviewer` - SUGGESTED_REVIEWER
 * * `urgent_for_project` - URGENT_FOR_PROJECT
 * * `dashboard_you_viewed` - DASHBOARD_YOU_VIEWED
 * * `dashboard_you_starred` - DASHBOARD_YOU_STARRED
 * * `insight_you_viewed` - INSIGHT_YOU_VIEWED
 * * `insight_you_starred` - INSIGHT_YOU_STARRED
 * * `alert_firing` - ALERT_FIRING
 * * `assigned_ticket` - ASSIGNED_TICKET
 * * `assigned_error_issue` - ASSIGNED_ERROR_ISSUE
 * * `review_requested` - REVIEW_REQUESTED
 * * `your_pull_request` - YOUR_PULL_REQUEST
 */
export type TodayItemReasonEnumApi = (typeof TodayItemReasonEnumApi)[keyof typeof TodayItemReasonEnumApi]

export const TodayItemReasonEnumApi = {
    ClaimedByYou: 'claimed_by_you',
    WaitingForYou: 'waiting_for_you',
    SuggestedReviewer: 'suggested_reviewer',
    UrgentForProject: 'urgent_for_project',
    DashboardYouViewed: 'dashboard_you_viewed',
    DashboardYouStarred: 'dashboard_you_starred',
    InsightYouViewed: 'insight_you_viewed',
    InsightYouStarred: 'insight_you_starred',
    AlertFiring: 'alert_firing',
    AssignedTicket: 'assigned_ticket',
    AssignedErrorIssue: 'assigned_error_issue',
    ReviewRequested: 'review_requested',
    YourPullRequest: 'your_pull_request',
} as const

/**
 * * `open` - OPEN
 * * `done` - DONE
 * * `dismissed` - DISMISSED
 */
export type BriefingItemStateEnumApi = (typeof BriefingItemStateEnumApi)[keyof typeof BriefingItemStateEnumApi]

export const BriefingItemStateEnumApi = {
    Open: 'open',
    Done: 'done',
    Dismissed: 'dismissed',
} as const

export interface BriefingItemApi {
    /** Stable item key, for example report:<uuid>, dashboard:<id> or ticket:<uuid>. */
    key: string
    /** The item's own title, as the source names it. */
    title: string
    /** Short left-bar label of at most 6 words. */
    label: string
    /** Short fact under the label, at most 40 characters, for example 'Spend down 37%'. */
    signal: string
    /** Where the item opens: an app path, or a GitHub URL for pull requests. */
    url: string
    /** Position in the briefing, 1 is the top item. */
    rank: number
    /**
     * For a report, the product its signals came from, for example error_tracking or session_replay. Null for every other item.
     * @nullable
     */
    source_product: string | null
    /** For a report, its priority, summary, implementation pull request and the metric snapshots the viewer may read. Null for every other item and for a deleted report. */
    report: BriefingItemReportApi | null
    group: TodayItemGroupEnumApi
    source: TodayItemSourceEnumApi
    reason: TodayItemReasonEnumApi
    /** `done` when the item was resolved since the briefing was written, `dismissed` when it was dismissed or suppressed, else `open`. Pull requests always stay `open`.
     *
     * * `open` - OPEN
     * * `done` - DONE
     * * `dismissed` - DISMISSED */
    state: BriefingItemStateEnumApi
}

/**
 * * `collecting` - COLLECTING
 * * `writing` - WRITING
 * * `ready` - READY
 * * `failed` - FAILED
 */
export type BriefingStatusEnumApi = (typeof BriefingStatusEnumApi)[keyof typeof BriefingStatusEnumApi]

export const BriefingStatusEnumApi = {
    Collecting: 'collecting',
    Writing: 'writing',
    Ready: 'ready',
    Failed: 'failed',
} as const

/**
 * * `agent` - AGENT
 */
export type WriterEnumApi = (typeof WriterEnumApi)[keyof typeof WriterEnumApi]

export const WriterEnumApi = {
    Agent: 'agent',
} as const

export interface BriefingApi {
    /** Briefing id. */
    id: string
    /** The day this briefing is for, in the person's timezone. */
    local_day: string
    /** One sentence that counts what needs the person. */
    headline: string
    /** Up to 3 paragraphs, each a list of text runs; runs with an item_key are links. */
    paragraphs: BriefingSegmentApi[][]
    /** The items the text names, in rank order: what the page and the left bar show. */
    items: BriefingItemApi[]
    /** Other open reports for the person, beyond the ones the briefing shows. */
    more_reports_count: number
    /** Open reports in the whole project beyond the ones the briefing shows, whoever they are for. */
    open_reports_count: number
    status: BriefingStatusEnumApi
    writer: WriterEnumApi | null
    created_at: string
    /** @nullable */
    ready_at: string | null
}

export interface CandidateFactApi {
    /** Fact name, for example pct_change or unread_messages. */
    name: string
    /** Fact value as text. */
    value: string
}

export interface CandidateApi {
    /** Stable item key, for example report:<uuid> or dashboard:<id>. */
    key: string
    /** The item's own title. */
    title: string
    /** Where the item opens. */
    url: string
    /** Position in the briefing, 1 is the top item. */
    rank: number
    /** The numbers and short facts the briefing text rests on. */
    facts: CandidateFactApi[]
    group: TodayItemGroupEnumApi
    source: TodayItemSourceEnumApi
    reason: TodayItemReasonEnumApi
}

export interface CandidateListApi {
    /** The day the list is for, in the person's timezone. */
    local_day: string
    /** The briefing's items in rank order, up to 5. */
    candidates: CandidateApi[]
    /** Other open reports for the person not in the list. */
    more_reports_count: number
}

export type TodayBriefingRetrieveParams = {
    /**
     * IANA timezone of the person's browser, for example Europe/Prague. The briefing day starts at 8:00 in it. Defaults to the project timezone.
     * @maxLength 64
     */
    timezone?: string
}

export type TodayBriefingRefreshCreateParams = {
    /**
     * IANA timezone of the person's browser, for example Europe/Prague. The briefing day starts at 8:00 in it. Defaults to the project timezone.
     * @maxLength 64
     */
    timezone?: string
}

export type TodayCandidatesRetrieveParams = {
    /**
     * IANA timezone of the person's browser, for example Europe/Prague. The briefing day starts at 8:00 in it. Defaults to the project timezone.
     * @maxLength 64
     */
    timezone?: string
}
