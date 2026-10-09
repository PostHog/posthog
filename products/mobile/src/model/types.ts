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
    mark: string
}

export interface InboxItem {
    id: string
    reportId: string
    title: string
    sourceProduct: SourceProduct
    sourceLabel: string
    accent: Accent
    updatedAt: string
    /** Today briefing rank, lowest first. Absent in the signals fallback. */
    rank?: number
    reason?: InboxReason
    state: InboxItemState
    needsInput: boolean
    read: boolean
    agent?: AgentBadge
    progressLabel?: string
    snoozeLabel?: string
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
          meta: string
          count: number
          url: string
      }

export interface Fact {
    key: string
    title: string
    sub?: string
    tone: 'default' | 'alert' | 'agent'
}

export interface MetricBar {
    value: number
    hot: boolean
}

export interface Metric {
    label: string
    range: string
    max: number
    bars: MetricBar[]
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
}

export interface PullRequestView {
    url: string
    number?: number
    title?: string
    state: 'open' | 'closed' | 'merged' | 'draft'
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
}

export type TaskRunStatus = 'not_started' | 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

export interface DecisionOption {
    id: string
    title: string
    meta?: string
}

export interface DecisionQuestion {
    id: string
    question: string
    options: DecisionOption[]
}

export interface TaskRunView {
    taskId: string
    runId?: string
    status: TaskRunStatus
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

export interface ReportView {
    id: string
    status?: ReportStatus
    priority?: ReportPriority
    summary?: string
    webUrl?: string
    canAct?: boolean
    suggestedPrompts?: string[]
    title: string
    sourceProduct: SourceProduct
    sourceLabel: string
    accent: Accent
    headline: Headline
    lede: string
    evidence: EvidenceBlock[]
    facts: Fact[]
    metric?: Metric
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

export type ActionBarState = 'idle' | 'handed' | 'decision' | 'decided' | 'pr_ready' | 'resolved'

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
}

export interface ReportActions {
    handOff: () => Promise<void>
    answerDecision: (input: DecisionAnswerInput) => Promise<void>
    undoDecision: () => Promise<void>
    snooze: (choice: SnoozeChoice) => Promise<void>
    /** Replaces the reviewers with the given user uuids. An empty list clears them. */
    setReviewers: (uuids: string[]) => Promise<void>
    markRead: () => Promise<void>
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

export interface ChatMessage {
    id: string
    role: 'user' | 'assistant'
    text: string
    at: string
}
