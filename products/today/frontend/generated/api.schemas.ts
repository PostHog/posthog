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
 * * `left` - LEFT
 */
export type BriefingItemStateEnumApi = (typeof BriefingItemStateEnumApi)[keyof typeof BriefingItemStateEnumApi]

export const BriefingItemStateEnumApi = {
    Open: 'open',
    Done: 'done',
    Dismissed: 'dismissed',
    Left: 'left',
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
    /** `done` when the item was resolved since the briefing was written, `dismissed` when it was dismissed or suppressed, `left` when the report no longer names the viewer as a suggested reviewer, else `open`. Pull requests always stay `open`.
     *
     * * `open` - OPEN
     * * `done` - DONE
     * * `dismissed` - DISMISSED
     * * `left` - LEFT */
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

export interface ExcerptChoiceRequestApi {
    /**
     * The finding the code excerpts should show.
     * @maxLength 6000
     */
    finding: string
    /**
     * Candidate code excerpts, best scored first.
     * @minItems 2
     * @maxItems 5
     * @items.maxLength 2000
     */
    excerpts: string[]
}

export interface ExcerptChoiceApi {
    /**
     * The excerpt that shows what the finding describes, or null when unsure.
     * @nullable
     */
    index: number | null
}

/**
 * * `lead` - Lead
 * * `impact` - Impact
 */
export type FigureTextEnumApi = (typeof FigureTextEnumApi)[keyof typeof FigureTextEnumApi]

export const FigureTextEnumApi = {
    Lead: 'lead',
    Impact: 'impact',
} as const

/**
 * * `signal` - Signal
 * * `research` - Agent's research
 */
export type FigureSourceKindEnumApi = (typeof FigureSourceKindEnumApi)[keyof typeof FigureSourceKindEnumApi]

export const FigureSourceKindEnumApi = {
    Signal: 'signal',
    Research: 'research',
} as const

/**
 * * `code` - Code
 * * `slack` - Slack
 */
export type CitedSourceEnumApi = (typeof CitedSourceEnumApi)[keyof typeof CitedSourceEnumApi]

export const CitedSourceEnumApi = {
    Code: 'code',
    Slack: 'slack',
} as const

export interface RecordingTargetApi {
    /** The recording's session id. */
    session_id: string
    /**
     * Where the player starts, a few seconds before the finding.
     * @nullable
     */
    start_at: string | null
    /**
     * The finding's time in the recording, as MM:SS.
     * @nullable
     */
    offset: string | null
    /**
     * Where the player starts, in seconds from the recording start. Null without an offset.
     * @nullable
     */
    seek_seconds: number | null
}

export interface PageLinkApi {
    /** Where the link goes, outside PostHog. */
    url: string
    /** The link text. */
    text: string
}

export interface CodeFileApi {
    /** The repository as owner/name. */
    repo: string
    /** The file path in the repository. */
    path: string
}

export interface PreviewLineApi {
    /** One line of the preview block. */
    text: string
    /** Whether the line is secondary, such as a stack frame. */
    quiet: boolean
}

export interface SignalPreviewApi {
    /** What expanding the signal shows, such as 'Show the stack trace'. */
    hint: string
    /** Repository files to quote, the finding's own file first. */
    code: CodeFileApi[]
    /** A preformatted block, such as a stack trace or a query. */
    block: PreviewLineApi[]
    /** The finding's text beyond its first sentence. */
    text: string
    /** Short facts about the source. */
    facts: string[]
    /** A link that replaces the signal's own destination. */
    link: PageLinkApi | null
    /**
     * A label that replaces the label of the signal's own destination.
     * @nullable
     */
    link_label: string | null
}

/**
 * The emitter's extra fields as it sent them, used to link to the source object. Values are any JSON.
 */
export type SignalViewApiExtra = { [key: string]: unknown }

export interface SignalViewApi {
    /** The signal's id. */
    signal_id: string
    /** The product that emitted the signal. */
    source_product: string
    /** The kind of signal within its product. */
    source_type: string
    /** The id of the source object, such as an issue or a ticket. */
    source_id: string
    /** The signal's text as emitted. */
    content: string
    /** When the signal happened. */
    timestamp: string
    /** The emitter's extra fields as it sent them, used to link to the source object. Values are any JSON. */
    extra: SignalViewApiExtra
    /** The signal as one short line. */
    headline: string
    /** The signal's first sentence. */
    lead: string
    /** Identifiers such as a pull request or ticket number, joined by dots. */
    meta: string
    /** What a scout finding cites: code or a Slack thread.
     *
     * * `code` - Code
     * * `slack` - Slack */
    cited: CitedSourceEnumApi | null
    /** The recording the signal plays, if any. */
    recording: RecordingTargetApi | null
    /** Where a scout finding links outside PostHog, if anywhere. */
    link: PageLinkApi | null
    /** What expanding the signal shows, if anything. */
    preview: SignalPreviewApi | null
}

export interface FigureQuoteApi {
    /** Where the number comes from: a signal or the agent's research.
     *
     * * `signal` - Signal
     * * `research` - Agent's research */
    kind: FigureSourceKindEnumApi
    /** The signal that states the number. Null when the agent's research states it. */
    signal: SignalViewApi | null
    /** When the source was written. */
    at: string
    /** The source sentence that states the number. */
    sentence: string
    /** Where the number starts in the sentence. */
    start: number
    /** Where the number ends in the sentence. */
    end: number
}

export interface FigureMarkApi {
    /** The page text the number is in: the lead or the impact sentence.
     *
     * * `lead` - Lead
     * * `impact` - Impact */
    text: FigureTextEnumApi
    /** Where the number starts in that text, as the reader sees it. */
    start: number
    /** Where the number ends in that text. */
    end: number
    /** The number as the page shows it. */
    figure: string
    /** The sentence that states the same result. */
    quote: FigureQuoteApi
}

export interface FigureMarksApi {
    /** The numbers to mark, at most 4, each with its source. */
    marks: FigureMarkApi[]
}

/**
 * * `problem` - Problem
 * * `cause` - Cause
 * * `fix` - Fix
 */
export type KeyClauseRoleEnumApi = (typeof KeyClauseRoleEnumApi)[keyof typeof KeyClauseRoleEnumApi]

export const KeyClauseRoleEnumApi = {
    Problem: 'problem',
    Cause: 'cause',
    Fix: 'fix',
} as const

export interface KeyClauseApi {
    /** Where the clause starts in its text, as the reader sees it. */
    start: number
    /** Where the clause ends in its text. */
    end: number
    /** What the clause tells the reader.
     *
     * * `problem` - Problem
     * * `cause` - Cause
     * * `fix` - Fix */
    role: KeyClauseRoleEnumApi
    /** Sentences from the report that explain the clause further. */
    expansion: string[]
}

export interface ReportKeyClausesApi {
    /** The clauses that state the problem or its cause in the lead. */
    lead: KeyClauseApi[]
    /** The clauses that state the problem or its cause in the impact sentence. */
    impact: KeyClauseApi[]
    /** The clause that states the fix in the proposal. */
    proposal: KeyClauseApi[]
}

export interface PullRequestLinkApi {
    /** The pull request on GitHub. */
    url: string
    /** The pull request number. */
    number: number
}

/**
 * * `tickets` - Support tickets
 * * `query-hours` - Database hours
 */
export type ImpactNumberKeyEnumApi = (typeof ImpactNumberKeyEnumApi)[keyof typeof ImpactNumberKeyEnumApi]

export const ImpactNumberKeyEnumApi = {
    Tickets: 'tickets',
    QueryHours: 'query-hours',
} as const

export interface ImpactWorkingApi {
    /** How the number is worked out, such as '120 ms × 30,000 calls'. */
    expression: string
    /** What the working comes to, such as '1.00 hours a day'. */
    result: string
}

export interface ImpactNumberApi {
    /** Which number this is: distinct support tickets or database hours a day.
     *
     * * `tickets` - Support tickets
     * * `query-hours` - Database hours */
    key: ImpactNumberKeyEnumApi
    /** The number as shown, such as '2' or '1 hour'. */
    value: string
    /** The sentence that follows the number. */
    sentence: string
    /** The signal the number comes from, if one does. */
    signal: SignalViewApi | null
    /** The figures in the signal's headline to mark. */
    values: string[]
    /** How the number is worked out, if it is. */
    working: ImpactWorkingApi | null
}

export interface ReportPageApi {
    /** The summary's opening paragraph, as markdown. */
    lead: string
    /** The proposed fix cut to whole sentences, as markdown. Empty when the report proposes none. */
    proposal: string
    /** The impact section cut to whole sentences, as markdown, when it states a measurement. Empty otherwise. */
    impact_sentence: string
    /** The pull request the proposal names, or else the summary, when it names exactly one. */
    named_pull_request: PullRequestLinkApi | null
    /** Whether the proposal names any pull request. */
    solution_names_pull_request: boolean
    /** The signals to show as evidence, at most 3, newest first, one per source first. */
    evidence: SignalViewApi[]
    /** How many distinct source objects the report's newest 100 signals come from. The impact numbers and last seen use the same signals. */
    source_count: number
    /** Numbers the signals size the problem with, such as distinct support tickets. */
    impact_numbers: ImpactNumberApi[]
    /**
     * When the newest session, ticket or alert behind the report happened.
     * @nullable
     */
    last_seen: string | null
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

export type TodayReportsKeyClausesRetrieveParams = {
    /**
     * Whether to mark the impact sentence. Pass false when the page shows an impact number instead.
     */
    include_impact?: boolean
}
