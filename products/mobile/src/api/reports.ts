import { ApiError, apiJson, projectPath } from './client'

// Shapes follow `products/signals/backend/serializers.py` and `report_read_state.py`, keeping the fields the app reads.

export interface ReportUserApi {
    uuid: string
    first_name: string
    last_name: string
    email: string
}

export interface ReportAssigneeApi {
    kind: 'user' | 'task' | 'agent' | 'system'
    user: ReportUserApi | null
    task_id: string | null
    agent: string | null
    claimed_at: string | null
}

export interface ReportPullRequestApi {
    url: string
    state: 'unknown' | 'draft' | 'open' | 'closed' | 'merged'
    merged: boolean
    review_decision: 'approved' | 'changes_requested' | 'review_required' | null
}

/** `ReportMetricSerializer`. `query` is only on the detail response, and null when redacted. */
export interface ReportMetricApi {
    metric_id: string
    title: string
    kind: string
    role: 'primary' | 'supporting'
    /** Null means no snapshot for this viewer, never zero. */
    value: number | null
    value_at: string | null
    /** Trailing per-bucket values, oldest first. */
    series: number[] | null
    value_format: 'number' | 'count' | 'percentage' | 'percentage_scaled' | 'duration' | 'currency'
    unit: string | null
    caption: string | null
    query?: unknown
}

export interface SignalReportApi {
    id: string
    title: string | null
    summary: string | null
    summary_lead: string
    status: string
    signal_count: number
    /** Snooze threshold: the report comes back when `signal_count` reaches it. */
    signals_at_run: number
    created_at: string
    updated_at: string
    metrics: ReportMetricApi[]
    suggested_prompts: string[]
    priority: string | null
    actionability: string | null
    already_addressed: boolean | null
    is_suggested_reviewer: boolean
    source_products: string[]
    scout_name: string | null
    implementation_pr_url: string | null
    pull_requests: ReportPullRequestApi[]
    work_state: 'unclaimed' | 'working' | 'in_review' | 'done'
    assignee: ReportAssigneeApi | null
}

export interface PaginatedApi<T> {
    count: number
    next: string | null
    results: T[]
}

export interface SignalNodeApi {
    signal_id: string
    content: string
    source_product: string
    source_type: string
    source_id: string
    timestamp: string
    extra: Record<string, unknown> | null
}

export interface ReportSignalsApi {
    signals: SignalNodeApi[]
}

/** `SignalReportArtefactSerializer`. `content` is parsed JSON; its shape depends on `type` (`artefact_schemas.py`). */
export interface ReportArtefactApi {
    id: string
    type: string
    content: unknown
    created_at: string
    actor_kind: 'user' | 'task' | 'agent' | 'system'
    actor_agent: string | null
    created_by: ReportUserApi | null
    task_id: string | null
}

export interface SuggestedReviewerApi {
    github_login: string | null
    user_uuid: string | null
    github_name: string | null
    user: ReportUserApi | null
}

/** `SuggestedReviewerEntryWriteSerializer`. One of the two keys is required. */
export interface SuggestedReviewerWriteApi {
    user_uuid?: string
    github_login?: string
}

export type AvailableReviewersApi = Record<string, { name: string; email: string }>

export interface ReadStatesApi {
    states: Record<string, boolean>
}

export interface ProjectScope {
    /** Base URL of the PostHog instance, without a trailing slash. */
    host: string
    projectId: number
}

export function isMissingFeature(error: unknown): boolean {
    return error instanceof ApiError && (error.status === 404 || error.status === 403)
}

export function retryUnlessMissing(failureCount: number, error: unknown): boolean {
    return !isMissingFeature(error) && failureCount < 1
}

type ScopeKey = readonly [string, number] | readonly ['none']

function scopeKey(scope: ProjectScope | null): ScopeKey {
    return scope ? [scope.host, scope.projectId] : ['none']
}

/** Query keys. Every key carries the host and project so a project switch never shows stale data. */
export const reportKeys = {
    all: (scope: ProjectScope | null) => ['signals', ...scopeKey(scope)] as const,
    briefingAll: (scope: ProjectScope | null) => ['today', ...scopeKey(scope), 'briefing'] as const,
    briefing: (scope: ProjectScope | null, timezone: string | null) =>
        [...reportKeys.briefingAll(scope), timezone] as const,
    inbox: (scope: ProjectScope | null) => [...reportKeys.all(scope), 'inbox'] as const,
    readStates: (scope: ProjectScope | null, ids: readonly string[]) =>
        [...reportKeys.all(scope), 'read_states', ids.join(',')] as const,
    readStatesAll: (scope: ProjectScope | null) => [...reportKeys.all(scope), 'read_states'] as const,
    report: (scope: ProjectScope | null, id: string) => [...reportKeys.all(scope), 'report', id] as const,
    detail: (scope: ProjectScope | null, id: string) => [...reportKeys.report(scope, id), 'detail'] as const,
    artefacts: (scope: ProjectScope | null, id: string) => [...reportKeys.report(scope, id), 'artefacts'] as const,
    signals: (scope: ProjectScope | null, id: string) => [...reportKeys.report(scope, id), 'signals'] as const,
    page: (scope: ProjectScope | null, id: string) => ['today', ...scopeKey(scope), 'page', id] as const,
    task: (scope: ProjectScope | null, taskId: string | undefined) =>
        ['tasks', ...scopeKey(scope), 'task', taskId ?? ''] as const,
    availableReviewers: (scope: ProjectScope | null, query: string) =>
        [...reportKeys.all(scope), 'available_reviewers', query] as const,
}

export const INBOX_REPORT_LIMIT = 50

// No `view=needs_decision`: that view drops a report once it has an implementation PR, and the reviewer of that PR
// still needs the report in the inbox.
export function fetchInboxReports(signal?: AbortSignal): Promise<PaginatedApi<SignalReportApi>> {
    return apiJson<PaginatedApi<SignalReportApi>>(projectPath('signals/reports/'), {
        query: { scope: 'for_me', status: 'ready,pending_input,failed', sort: 'priority', limit: INBOX_REPORT_LIMIT },
        signal,
    })
}

export function fetchReport(reportId: string, signal?: AbortSignal): Promise<SignalReportApi> {
    return apiJson<SignalReportApi>(projectPath(`signals/reports/${encodeURIComponent(reportId)}/`), { signal })
}

export function fetchReportSignals(reportId: string, signal?: AbortSignal): Promise<ReportSignalsApi> {
    return apiJson<ReportSignalsApi>(projectPath(`signals/reports/${encodeURIComponent(reportId)}/signals/`), {
        signal,
    })
}

export const ARTEFACT_PAGE_SIZE = 100

/** `GET signals/reports/{id}/artefacts/`, newest first. */
export function fetchReportArtefacts(reportId: string, signal?: AbortSignal): Promise<PaginatedApi<ReportArtefactApi>> {
    return apiJson<PaginatedApi<ReportArtefactApi>>(
        projectPath(`signals/reports/${encodeURIComponent(reportId)}/artefacts/`),
        {
            query: { limit: ARTEFACT_PAGE_SIZE },
            signal,
        }
    )
}

/** `read_state/` accepts at most this many ids per request. */
export const READ_STATE_BATCH = 100

/** Without `read` this only reads the states; with it, it sets them for the current user and returns the new states. */
export function postReadStates(reportIds: string[], read?: boolean, signal?: AbortSignal): Promise<ReadStatesApi> {
    return apiJson<ReadStatesApi>(projectPath('signals/reports/read_state/'), {
        method: 'POST',
        json: read === undefined ? { report_ids: reportIds } : { report_ids: reportIds, read },
        signal,
    })
}

/** `POST signals/reports/{id}/state/` with `potential`: hides the report until `count` more signals arrive. */
export function snoozeReportForSignals(reportId: string, count: number): Promise<SignalReportApi> {
    return apiJson<SignalReportApi>(projectPath(`signals/reports/${encodeURIComponent(reportId)}/state/`), {
        method: 'POST',
        json: { state: 'potential', snooze_for: count },
    })
}

/** `PUT signals/reports/{id}/reviewers/`: replaces the suggested reviewers. Returns the new artefact. */
export function putReportReviewers(reportId: string, content: SuggestedReviewerWriteApi[]): Promise<ReportArtefactApi> {
    return apiJson<ReportArtefactApi>(projectPath(`signals/reports/${encodeURIComponent(reportId)}/reviewers/`), {
        method: 'PUT',
        json: { content },
    })
}

export function fetchAvailableReviewers(query: string, signal?: AbortSignal): Promise<AvailableReviewersApi> {
    return apiJson<AvailableReviewersApi>(projectPath('signals/reports/available_reviewers/'), {
        query: { query: query || undefined },
        signal,
    })
}
