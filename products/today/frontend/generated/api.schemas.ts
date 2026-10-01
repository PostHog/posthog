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
 */
export type BriefingItemStateEnumApi = (typeof BriefingItemStateEnumApi)[keyof typeof BriefingItemStateEnumApi]

export const BriefingItemStateEnumApi = {
    Open: 'open',
    Done: 'done',
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
    /** Position in the full ranked list, 1 is the most important. */
    rank: number
    /**
     * For a report, the product its signals came from, for example error_tracking or session_replay. Null for every other item.
     * @nullable
     */
    source_product: string | null
    group: TodayItemGroupEnumApi
    source: TodayItemSourceEnumApi
    reason: TodayItemReasonEnumApi
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
 * * `llm` - LLM
 * * `template` - TEMPLATE
 */
export type WriterEnumApi = (typeof WriterEnumApi)[keyof typeof WriterEnumApi]

export const WriterEnumApi = {
    Llm: 'llm',
    Template: 'template',
} as const

/**
 * * `morning` - MORNING
 * * `midday` - MIDDAY
 */
export type EditionEnumApi = (typeof EditionEnumApi)[keyof typeof EditionEnumApi]

export const EditionEnumApi = {
    Morning: 'morning',
    Midday: 'midday',
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
    /** 'morning' from 8:00, or 'midday' from 12:00, in the person's timezone.
     *
     * * `morning` - MORNING
     * * `midday` - MIDDAY */
    edition: EditionEnumApi
    created_at: string
    /** @nullable */
    ready_at: string | null
}

export interface TodayErrorApi {
    /** What went wrong. */
    detail: string
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
    /** Position in the ranked list, 1 is the most important. */
    rank: number
    /** True when the item is one of the top 5 the briefing text covers. */
    in_text: boolean
    /** The numbers and short facts the ranking used. */
    facts: CandidateFactApi[]
    group: TodayItemGroupEnumApi
    source: TodayItemSourceEnumApi
    reason: TodayItemReasonEnumApi
}

export interface CandidateListApi {
    /** The day the list is for, in the person's timezone. */
    local_day: string
    /** Up to 10 items in rank order. */
    candidates: CandidateApi[]
    /** Other open reports for the person not in the list. */
    more_reports_count: number
    /** Sources that failed, so their items are missing. */
    failed_sources: string[]
}

export type TodayBriefingRetrieveParams = {
    /**
     * IANA timezone of the person's browser, for example Europe/Prague. Editions start at 8:00 and 12:00 in it. Defaults to the project timezone.
     * @maxLength 64
     */
    timezone?: string
}

export type TodayBriefingRefreshCreateParams = {
    /**
     * IANA timezone of the person's browser, for example Europe/Prague. Editions start at 8:00 and 12:00 in it. Defaults to the project timezone.
     * @maxLength 64
     */
    timezone?: string
}

export type TodayCandidatesRetrieveParams = {
    /**
     * IANA timezone of the person's browser, for example Europe/Prague. Editions start at 8:00 and 12:00 in it. Defaults to the project timezone.
     * @maxLength 64
     */
    timezone?: string
}
