/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
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
 * * `computing` - Computing
 * * `ready` - Ready
 * * `failed` - Failed
 */
export type HighlightsStatusEnumApi = (typeof HighlightsStatusEnumApi)[keyof typeof HighlightsStatusEnumApi]

export const HighlightsStatusEnumApi = {
    Computing: 'computing',
    Ready: 'ready',
    Failed: 'failed',
} as const

/**
 * * `events` - Events
 * * `people` - People
 * * `number` - Number
 */
export type HighlightUnitEnumApi = (typeof HighlightUnitEnumApi)[keyof typeof HighlightUnitEnumApi]

export const HighlightUnitEnumApi = {
    Events: 'events',
    People: 'people',
    Number: 'number',
} as const

/**
 * * `day` - Day
 * * `week` - Week
 * * `month` - Month
 */
export type CalendarUnitEnumApi = (typeof CalendarUnitEnumApi)[keyof typeof CalendarUnitEnumApi]

export const CalendarUnitEnumApi = {
    Day: 'day',
    Week: 'week',
    Month: 'month',
} as const

export interface HighlightValueFormatApi {
    /**
     * Number format of the insight, for example numeric, percentage or currency.
     * @nullable
     */
    format: string | null
    /**
     * Text the insight shows before each value.
     * @nullable
     */
    prefix: string | null
    /**
     * Text the insight shows after each value.
     * @nullable
     */
    postfix: string | null
    /**
     * Most decimal places the insight shows.
     * @nullable
     */
    decimal_places: number | null
}

/**
 * * `routine` - You open this often
 * * `dashboard` - On a dashboard you open often
 * * `key_metric` - Project key metric
 */
export type HighlightMetricReasonEnumApi =
    (typeof HighlightMetricReasonEnumApi)[keyof typeof HighlightMetricReasonEnumApi]

export const HighlightMetricReasonEnumApi = {
    Routine: 'routine',
    Dashboard: 'dashboard',
    KeyMetric: 'key_metric',
} as const

export interface HighlightMoverApi {
    /** Name of one series of the insight, for example a breakdown value. */
    label: string
    /** Value of the series for the last complete period. */
    value: number
    /**
     * Change of the series against the period before, in percent. Null when the period before is 0.
     * @nullable
     */
    change_pct: number | null
}

export interface HighlightMetricApi {
    /** Stable key of the metric: a key metric setting such as signup_event, or insight:<short_id>. */
    key: string
    /** Name of the key metric or of the insight, for example Sign-ups. */
    name: string
    /** Value for the last complete period: the last 7 complete days, or the last complete week or month. */
    value: number
    /** `events` for a count of events, `people` for unique people, `number` for an insight value.
     *
     * * `events` - Events
     * * `people` - People
     * * `number` - Number */
    unit: HighlightUnitEnumApi
    /**
     * Change against the period before, in percent. Null when the period before is 0.
     * @nullable
     */
    change_pct: number | null
    /** Values oldest first: daily for the last 28 complete days, or one value per week or month. */
    series: number[]
    /** What one value in `series` covers: a day, a week or a month.
     *
     * * `day` - Day
     * * `week` - Week
     * * `month` - Month */
    interval: CalendarUnitEnumApi
    /**
     * Path of the insight the metric comes from. For a key metric, a new trends insight of the same days.
     * @nullable
     */
    url: string | null
    /** How the insight formats its values. Null for a key metric and for an insight with plain numbers. */
    value_format: HighlightValueFormatApi | null
    /** The first day of the period each value in `series` covers, in the project's timezone. Same length and order as `series`. */
    period_starts: string[]
    /** Why the pulse suggests the metric: `routine` for an insight the person opens often, `dashboard` for a tile of a dashboard they open often, `key_metric` for a key metric of the project. Null for a number the person pinned, which `pins` lists, and for metrics computed before this field existed.
     *
     * * `routine` - You open this often
     * * `dashboard` - On a dashboard you open often
     * * `key_metric` - Project key metric */
    reason: HighlightMetricReasonEnumApi | null
    /**
     * Name of the dashboard the tile comes from when `reason` is `dashboard`, else null.
     * @nullable
     */
    dashboard_name: string | null
    /**
     * Id of the dashboard the tile comes from, with its filters applied. Pass it when pinning the tile. Null otherwise.
     * @nullable
     */
    dashboard_id: number | null
    /**
     * On how many of the last 14 days the person opened the insight, or the dashboard of the tile. Null for a key metric.
     * @nullable
     */
    opened_days: number | null
    /**
     * The last day the person opened the insight, or the dashboard of the tile, in the project's timezone. Null for a key metric.
     * @nullable
     */
    last_opened: string | null
    /**
     * Value for the period before the last complete one, the base of `change_pct`. Null when unknown.
     * @nullable
     */
    previous_value: number | null
    /** For an insight with several series, the series that changed most last period, biggest change first. Empty otherwise. */
    movers: HighlightMoverApi[]
}

/**
 * * `risk` - Risk
 * * `opportunity` - Opportunity
 */
export type HighlightLabelEnumApi = (typeof HighlightLabelEnumApi)[keyof typeof HighlightLabelEnumApi]

export const HighlightLabelEnumApi = {
    Risk: 'risk',
    Opportunity: 'opportunity',
} as const

/**
 * * `P1` - P1
 * * `P2` - P2
 * * `P3` - P3
 * * `P4` - P4
 */
export type HighlightPriorityEnumApi = (typeof HighlightPriorityEnumApi)[keyof typeof HighlightPriorityEnumApi]

export const HighlightPriorityEnumApi = {
    P1: 'P1',
    P2: 'P2',
    P3: 'P3',
    P4: 'P4',
} as const

export interface HighlightItemApi {
    /** Stable key of the item for this person and day. */
    key: string
    /** `risk` when something got worse or broke, `opportunity` when the person can act to gain.
     *
     * * `risk` - Risk
     * * `opportunity` - Opportunity */
    label: HighlightLabelEnumApi
    /** Priority on the same scale as report priorities. `P1` for a risk with a score of 0.75 or more, `P2` for another risk, `P3` for an opportunity with a score of 0.4 or more, `P4` for another opportunity.
     *
     * * `P1` - P1
     * * `P2` - P2
     * * `P3` - P3
     * * `P4` - P4 */
    priority: HighlightPriorityEnumApi
    /** One sentence that says what happened, with numbers. */
    title: string
    /** One or two short sentences with the comparison and the next action. */
    detail: string
    /**
     * Path in the app to open, relative to the project.
     * @nullable
     */
    url: string | null
    /**
     * Values behind the item for a small trend line, oldest first. Null when the item has no trend.
     * @nullable
     */
    series: number[] | null
    /** Importance weighted by relevance, from 0 to 1. */
    score: number
    /** Name of the highlight source that found the item, for example alerts. */
    source: string
}

/**
 * * `ready` - Ready
 * * `unavailable` - Unavailable
 */
export type HighlightPinStatusEnumApi = (typeof HighlightPinStatusEnumApi)[keyof typeof HighlightPinStatusEnumApi]

export const HighlightPinStatusEnumApi = {
    Ready: 'ready',
    Unavailable: 'unavailable',
} as const

export interface HighlightPinApi {
    /** Key of a number the person keeps on their home. */
    key: string
    /** `ready` when the number is in `pulse`. `unavailable` when it has no number to show, for example a deleted insight, one that is not a trend, or a query that failed or did not finish in time. A pin missing from this list was added after these highlights were computed.
     *
     * * `ready` - Ready
     * * `unavailable` - Unavailable */
    status: HighlightPinStatusEnumApi
}

export interface HighlightsApi {
    /** `ready` when the content is fresh. `computing` while new highlights are being computed: the content is the last ready highlights of the day, or empty, so poll again every 2 seconds until the status changes. `failed` when the last computation failed: the content is the last ready highlights of the day, or empty.
     *
     * * `computing` - Computing
     * * `ready` - Ready
     * * `failed` - Failed */
    status: HighlightsStatusEnumApi
    /**
     * When the content was computed. Null when no highlights were computed yet today.
     * @nullable
     */
    generated_at: string | null
    /** The day the highlights are for, in the project's timezone. */
    day: string
    /** Midnight at the end of `day` in the project's timezone, when the next day's highlights start. Load them again then. */
    refresh_at: string
    /** Key metrics of the project from its settings. */
    pulse: HighlightMetricApi[]
    /** Up to 6 items, the highest scores across sources, in display order: by `priority`, then by `score`, highest first. */
    items: HighlightItemApi[]
    /** The numbers the person keeps, in their order, with the state of each one. Pinned numbers lead `pulse`. */
    pins: HighlightPinApi[]
}

export interface PulsePinApi {
    /**
     * Key of the number to keep: a key metric setting such as signup_event, or insight:<short_id>.
     * @maxLength 200
     */
    key: string
    /**
     * Name to show for the number until the highlights compute its value.
     * @maxLength 400
     */
    name: string
    /**
     * For an insight pinned from a dashboard tile, the dashboard whose filters it keeps. Null otherwise.
     * @nullable
     */
    dashboard_id?: number | null
}

export interface PulsePinsApi {
    /** Numbers the person keeps at the start of the key numbers, in order. Suggestions fill the free places. Only the first 4 distinct keys are kept. At most 20 entries. */
    pins: PulsePinApi[]
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

export type TodayReportsKeyClausesRetrieveParams = {
    /**
     * Whether to mark the impact sentence. Pass false when the page shows an impact number instead.
     */
    include_impact?: boolean
}
