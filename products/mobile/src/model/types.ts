import type { DismissReason, ResolveReason } from './verdictReasons'

// Every timestamp in these view models is an ISO 8601 string; screens format it at render time.

/** `alert`: something is wrong. `opportunity`: feedback or a request. `resolved`: fixed or closed. */
export type Accent = 'alert' | 'opportunity' | 'resolved'

// `SignalSourceProduct` values from `products/signals/backend/enums.py`, plus `dashboard` for Today dashboard items
// (no source product) and `other`, which adapters use for unknown server values instead of widening this union.
export type SourceProduct =
    | 'error_tracking'
    | 'github'
    | 'gitlab'
    | 'pganalyze'
    | 'analytics'
    | 'session_replay'
    | 'replay_vision'
    | 'llm_analytics'
    | 'logs'
    | 'health_checks'
    | 'signals_scout'
    | 'signals_check'
    | 'endpoints'
    | 'conversations'
    | 'zendesk'
    | 'intercom'
    | 'linear'
    | 'jira'
    | 'sentry'
    | 'engineering_analytics'
    | 'dashboard'
    | 'other'

export type InboxReason =
    | 'claimed_by_you'
    | 'waiting_for_you'
    | 'suggested_reviewer'
    | 'urgent_for_project'
    | 'review_requested'
    | 'your_pull_request'
    | 'other'

/** `snoozed` is app-side: a local time snooze, or a signal-count snooze the server reports as `potential`. */
export type InboxItemState = 'open' | 'done' | 'dismissed' | 'left' | 'snoozed'

export interface AgentBadge {
    name: string
}

export interface InboxItem {
    id: string
    reportId: string
    title: string
    sourceProduct: SourceProduct
    sourceLabel: string
    /** Raw `source_products` of the report, for the source filter. */
    sources: readonly string[]
    accent: Accent
    createdAt: string
    updatedAt: string
    /** The served ranking model's merge probability, for the model score sort. Null when unscored or hidden. */
    modelScore: number | null
    reason?: InboxReason
    state: InboxItemState
    needsInput: boolean
    read: boolean
    agent?: AgentBadge
    progressLabel?: string
    snoozeLabel?: string
    /** The report's primary pull request, known from the list payload before the report detail loads. */
    pullRequestUrl?: string
    /** That pull request's state, when the list payload carries it. */
    pullRequestState?: PullRequestView['state']
}

export interface Headline {
    number?: string
    rest: string
}

export interface TraceFrame {
    fn: string
    loc: string
}

export interface Quote {
    text: string
    who: string
}

export type EvidenceBlock =
    | {
          kind: 'trace'
          error: string
          frames: TraceFrame[]
          footer?: string
      }
    | { kind: 'quotes'; quotes: Quote[] }
    | {
          kind: 'replay'
          sessionId: string
          /** Seconds into the recording where the evidence happens, when the signal names it. */
          t?: number
          meta: string
          count: number
          /** The web player. The demo opens it, because its sessions do not exist in a project. */
          url: string
      }

export interface Fact {
    key: string
    title: string
    sub?: string
    tone: 'default' | 'alert' | 'agent'
}

export type MetricChartKind = 'line' | 'bar'

export type MetricInterval = 'hour' | 'day' | 'week' | 'month'

export type MetricValueFormat = 'number' | 'count' | 'percentage' | 'percentage_scaled' | 'duration' | 'currency'

export interface MetricFormat {
    valueFormat: MetricValueFormat
    unit: string | null
}

/** One dated bucket. `value` is NaN when the bucket has no data. */
export interface MetricPoint {
    at: string
    value: number
}

export interface MetricSeries {
    points: MetricPoint[]
    interval: MetricInterval
}

/** The saved value the server measured last. `series` holds at most 14 undated trailing buckets. */
export interface MetricSnapshot {
    value: number
    at: string | null
    series: number[]
}

/** Where the live number and series come from. `query` runs through the query endpoint; `static` is fixture data; `none` means redacted. */
export type MetricData =
    | { kind: 'query'; seriesQuery: unknown; aggregateQuery: unknown }
    | { kind: 'static'; series: MetricSeries; value: number }
    | { kind: 'none' }

export interface MetricView {
    metricId: string
    role: 'primary' | 'supporting'
    title: string
    caption?: string
    format: MetricFormat
    chart: MetricChartKind
    interval: MetricInterval
    snapshot?: MetricSnapshot
    data: MetricData
    /** "Last 14 days", or "Current window" when the query has no relative window. */
    windowLabel: string
    filterCount: number
    openUrl?: string
}

export interface ReportChartView {
    chartId: string
    title: string
    caption?: string
    /** Present only for a trends query the app can draw. */
    data?: Extract<MetricData, { kind: 'query' } | { kind: 'static' }>
    format: MetricFormat
    chart: MetricChartKind
    interval: MetricInterval
    openUrl?: string
}

/** One signal behind a report, for the full report screen. */
export interface ReportSignalView {
    id: string
    sourceProduct: SourceProduct
    sourceLabel: string
    /** Plain text or light markdown, often with a fenced stack trace. */
    content: string
    at: string
    sessionId?: string
    /** The recording on the web. Set when `sessionId` is. */
    replayUrl?: string
    ticketNumber?: number
}

export interface ActivityEvent {
    id: string
    /** Sentence with `**bold**` segments, for example "Alex Kim handed off to **PostHog**". */
    text: string
    at: string
    via?: string
}

export type WorkState = 'unclaimed' | 'working' | 'in_review' | 'done'

export interface WorkAssignee {
    kind: 'user' | 'task' | 'agent' | 'system'
    name: string
    taskId?: string
    claimId?: string
}

export interface PullRequestView {
    id?: string
    url: string
    number?: number
    title?: string
    state: 'open' | 'closed' | 'merged' | 'draft' | 'unknown'
    reviewDecision?: 'approved' | 'changes_requested' | 'review_required'
    filesChanged?: number
    additions?: number
    deletions?: number
    checksPassed?: boolean
    note?: string
}

export interface WorkView {
    state: WorkState
    assignee?: WorkAssignee
    pullRequest?: PullRequestView
    pullRequests?: PullRequestView[]
}

export type TaskRunStatus = 'not_started' | 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

export interface DecisionOption {
    id: string
    title: string
    meta?: string
}

export interface DecisionQuestion {
    details?: string
    id: string
    question: string
    options: DecisionOption[]
}

export interface TaskRunView {
    taskId: string
    runId?: string
    status: TaskRunStatus
    phase?: 'working' | 'idle' | 'unknown'
    connection?: 'connecting' | 'connected' | 'reconnecting' | 'unavailable'
    stage?: string
    pendingDecision?: DecisionQuestion
}

export interface Reviewer {
    uuid: string
    name: string
    email: string
}

export type ReportStatus =
    | 'potential'
    | 'candidate'
    | 'in_progress'
    | 'pending_input'
    | 'ready'
    | 'resolved'
    | 'failed'
    | 'deleted'
    | 'suppressed'

export type ReportPriority = 'P0' | 'P1' | 'P2' | 'P3' | 'P4'

/** Who owns the report now. `agent` covers PostHog's own tasks and external agents such as Claude Code. */
export type ReportOwner = { kind: 'none' } | { kind: 'user' | 'agent'; name: string }

export interface ReportView {
    id: string
    status?: ReportStatus
    priority?: ReportPriority
    summary?: string
    webUrl?: string
    repository?: string
    canAct?: boolean
    suggestedPrompts?: string[]
    title: string
    sourceProduct: SourceProduct
    sourceLabel: string
    accent: Accent
    headline: Headline
    lede: string
    evidence: EvidenceBlock[]
    /** When the report started, as display text ("Mon 3:05 PM", "Today 9:04 AM", "Just now"). */
    since?: string
    owner: ReportOwner
    /** The facts that are not shown elsewhere on the screen, such as Impact. */
    facts: Fact[]
    observation?: MetricView
    supportingMetrics: MetricView[]
    charts: ReportChartView[]
    /** Every signal of the report, newest first. */
    signals: ReportSignalView[]
    activity: ActivityEvent[]
    work: WorkView
    task?: TaskRunView
    reviewers: Reviewer[]
    prompt: string
    contextNote: string
}

export interface Person {
    uuid: string
    name: string
    email: string
    role?: string
    color?: string
}

export interface DecisionAnswer {
    questionId: string
    optionId?: string
    text: string
    meta?: string
}

export interface ActionBarState {
    pullRequests: PullRequestView[]
    activity?: { title: string; meta?: string; tone: 'working' | 'idle' | 'stopped' }
    request?: DecisionQuestion
    showHandoff: boolean
    answer?: DecisionAnswer
}

export interface ActionBarLocalState {
    answer?: DecisionAnswer
    handOffPending?: boolean
}

export type SnoozePreset = 'hour' | 'tomorrow' | 'next_week' | 'month' | 'custom'

/** `signals` snoozes on the server until `count` more signals arrive; `until` snoozes on the device with a reminder. */
export type SnoozeChoice = { kind: 'signals'; count: number } | { kind: 'until'; preset: SnoozePreset; until: string }

export interface DecisionAnswerInput {
    questionId: string
    optionId?: string
    text: string
}

export interface ReportActionsPending {
    handOff: boolean
    answer: boolean
    snooze: boolean
    reviewers: boolean
    priority: boolean
    resolve: boolean
    dismiss: boolean
}

export interface ReportActions {
    handOff: () => Promise<void>
    answerDecision: (input: DecisionAnswerInput) => Promise<void>
    undoDecision: () => Promise<void>
    snooze: (choice: SnoozeChoice) => Promise<void>
    /** Marks the report done. The server closes its open implementation PR. */
    resolve: (reason: ResolveReason, note: string) => Promise<void>
    /** Takes the report out of the inbox. The agent that filed it reads the note on its next run. */
    dismiss: (reason: DismissReason, note: string) => Promise<void>
    /** Replaces the reviewers with the given user uuids. An empty list clears them. */
    setReviewers: (uuids: string[]) => Promise<void>
    setPriority: (priority: ReportPriority) => Promise<void>
    markRead: () => Promise<void>
    markUnread: () => Promise<void>
    pending: ReportActionsPending
}

export interface QueryState<T> {
    data: T | undefined
    isLoading: boolean
    isError: boolean
    error: Error | null
    isRefetching: boolean
    refetch: () => unknown
}

export type ChatSessionStatus = 'working' | 'queued' | 'starting' | 'completed' | 'failed' | 'stopped' | 'idle'

/** Where a session started: a PostHog AI chat, a report hand-off, or anything else. */
export type ChatOrigin = 'chat' | 'report' | 'session'

export interface ChatListItem {
    /** Stable list key: `session:<task id>`. */
    id: string
    kind: 'session'
    /** The task id. */
    sourceId: string
    origin: ChatOrigin
    /** Never empty: "Untitled session" when the server has no title. */
    title: string
    /** ISO time of the last activity. The list sorts and groups by it. */
    updatedAt: string
    status: ChatSessionStatus
    pullRequestUrl: string | null
    /** The session in the web app (`ai?task=`). Undefined without a project scope, as in demo mode. */
    webUrl?: string
}

export interface ChatGroup {
    label: string
    items: ChatListItem[]
}
