import type { ReportPriority } from '@/model/types'
import { type DismissReason, type ResolveReason, VERDICT_NOTE_MAX_LENGTH } from '@/model/verdictReasons'
import type {
    PullRequestChecksResponseApi,
    SignalsReportsListParams,
} from '../../../signals/frontend/generated/api.schemas'

import { ApiError, apiJson, apiUrl, projectPath } from './client'

// Shapes follow `products/signals/backend/serializers.py` and `report_read_state.py`, keeping the fields the app reads.

export interface ReportUserApi {
    uuid: string
    first_name: string
    last_name: string
    email: string
}

export interface ReportAssigneeApi {
    claim_id?: string | null
    kind: 'user' | 'task' | 'agent' | 'system'
    user: ReportUserApi | null
    task_id: string | null
    agent: string | null
    claimed_at: string | null
}

export interface ReportPullRequestApi {
    id?: string | null
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
    /** An `InsightVizNode` with a `TrendsQuery` source. */
    query?: unknown
}

export interface ReportChartApi {
    chart_id: string
    title: string
    /** An `InsightVizNode`, a `DataVisualizationNode` (a `HogQLQuery` source) or a `SavedInsightNode` (a `shortId`). */
    query: unknown
    caption?: string | null
    size?: 'small' | 'medium' | 'large' | null
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
    charts: ReportChartApi[]
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
    /** `ReportRankingSerializer`: outcome head name (such as `pr_merged`) to its probability. Null for non-staff users. */
    ranking?: { scores: Record<string, number> } | null
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

export type ScopeKey = readonly [string, number] | readonly ['none']

export function scopeKey(scope: ProjectScope | null): ScopeKey {
    return scope ? [scope.host, scope.projectId] : ['none']
}

/** Query keys. Every key carries the host and project so a project switch never shows stale data. */
export const reportKeys = {
    all: (scope: ProjectScope | null) => ['signals', ...scopeKey(scope)] as const,
    inbox: (scope: ProjectScope | null) => [...reportKeys.all(scope), 'inbox'] as const,
    readStates: (scope: ProjectScope | null, ids: readonly string[]) =>
        [...reportKeys.all(scope), 'read_states', ids.join(',')] as const,
    readStatesAll: (scope: ProjectScope | null) => [...reportKeys.all(scope), 'read_states'] as const,
    report: (scope: ProjectScope | null, id: string) => [...reportKeys.all(scope), 'report', id] as const,
    detail: (scope: ProjectScope | null, id: string) => [...reportKeys.report(scope, id), 'detail'] as const,
    artefacts: (scope: ProjectScope | null, id: string) => [...reportKeys.report(scope, id), 'artefacts'] as const,
    reviewers: (scope: ProjectScope | null, id: string) => [...reportKeys.artefacts(scope, id), 'reviewers'] as const,
    signals: (scope: ProjectScope | null, id: string) => [...reportKeys.report(scope, id), 'signals'] as const,
    page: (scope: ProjectScope | null, id: string) => ['today', ...scopeKey(scope), 'page', id] as const,
    task: (scope: ProjectScope | null, taskId: string | undefined) =>
        ['tasks', ...scopeKey(scope), 'task', taskId ?? ''] as const,
    availableReviewers: (scope: ProjectScope | null, query: string) =>
        [...reportKeys.all(scope), 'available_reviewers', query] as const,
}

export interface InboxPageApi {
    results: SignalReportApi[]
    count: number
    next?: string | null
}

export const INBOX_PAGE_SIZE = 20

export function fetchInboxPage(offset: number, signal?: AbortSignal): Promise<InboxPageApi> {
    return apiJson<InboxPageApi>(projectPath('signals/reports/'), {
        query: { view: 'for_you', sort: 'priority', limit: INBOX_PAGE_SIZE, offset } satisfies SignalsReportsListParams,
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
export function fetchReportArtefacts(
    reportId: string,
    signal?: AbortSignal,
    offset = 0
): Promise<PaginatedApi<ReportArtefactApi>> {
    return apiJson<PaginatedApi<ReportArtefactApi>>(
        projectPath(`signals/reports/${encodeURIComponent(reportId)}/artefacts/`),
        {
            query: { limit: ARTEFACT_PAGE_SIZE, ...(offset ? { offset } : {}) },
            signal,
        }
    )
}

/** Find the latest full reviewer assignment, which may be older than the first artefact page. */
export async function fetchLatestReviewerArtefact(
    reportId: string,
    signal?: AbortSignal
): Promise<ReportArtefactApi | null> {
    const path = projectPath(`signals/reports/${encodeURIComponent(reportId)}/artefacts/`)
    const firstUrl = new URL(apiUrl(path))
    let offset = 0
    for (;;) {
        const page = await fetchReportArtefacts(reportId, signal, offset)
        const reviewer = page.results.find((artefact) => artefact.type === 'suggested_reviewers')
        if (reviewer || !page.next) {
            return reviewer ?? null
        }
        const next = new URL(page.next, firstUrl)
        const nextOffset = Number(next.searchParams.get('offset'))
        if (
            next.origin !== firstUrl.origin ||
            next.pathname !== firstUrl.pathname ||
            !Number.isSafeInteger(nextOffset) ||
            nextOffset <= offset
        ) {
            throw new Error('Invalid report artefact page')
        }
        offset = nextOffset
    }
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

function postVerdict(
    reportId: string,
    state: 'resolved' | 'suppressed',
    reason: ResolveReason | DismissReason,
    note = ''
): Promise<SignalReportApi> {
    const trimmed = note.trim().slice(0, VERDICT_NOTE_MAX_LENGTH)
    return apiJson<SignalReportApi>(projectPath(`signals/reports/${encodeURIComponent(reportId)}/state/`), {
        method: 'POST',
        json: { state, dismissal_reason: reason, ...(trimmed ? { dismissal_note: trimmed } : {}) },
    })
}

/**
 * `POST signals/reports/{id}/state/` with `resolved`: marks the report done and closes its open implementation PR.
 * A 409 means the report's current status cannot move to resolved; its `error` says why.
 */
export function resolveReport(reportId: string, reason: ResolveReason, note?: string): Promise<SignalReportApi> {
    return postVerdict(reportId, 'resolved', reason, note)
}

/**
 * `POST signals/reports/{id}/state/` with `suppressed`: the report leaves the inbox, and the agent that filed it reads
 * the note on its next run. A 409 means the report's current status cannot move to suppressed; its `error` says why.
 */
export function dismissReport(reportId: string, reason: DismissReason, note?: string): Promise<SignalReportApi> {
    return postVerdict(reportId, 'suppressed', reason, note)
}

/** `PUT signals/reports/{id}/reviewers/`: replaces the suggested reviewers. Returns the new artefact. */
export function putReportReviewers(reportId: string, content: SuggestedReviewerWriteApi[]): Promise<ReportArtefactApi> {
    return apiJson<ReportArtefactApi>(projectPath(`signals/reports/${encodeURIComponent(reportId)}/reviewers/`), {
        method: 'PUT',
        json: { content },
    })
}

/** `SignalReportArtefactWriteResponseSerializer`: the stored row, without the actor fields of the read shape. */
export interface ReportArtefactWriteApi {
    id: string
    report_id: string
    type: string
    content: unknown
    created_at: string
    task_id: string | null
}

/** `PriorityAssessment` requires a non-empty explanation. */
export const MANUAL_PRIORITY_EXPLANATION = 'Priority set by hand from the PostHog mobile app'

/** `POST signals/reports/{id}/artefacts/` with a `priority_judgment`: the newest one is the report's priority. */
export function postPriorityJudgment(reportId: string, priority: ReportPriority): Promise<ReportArtefactWriteApi> {
    return apiJson<ReportArtefactWriteApi>(projectPath(`signals/reports/${encodeURIComponent(reportId)}/artefacts/`), {
        method: 'POST',
        json: { artefact_type: 'priority_judgment', content: { priority, explanation: MANUAL_PRIORITY_EXPLANATION } },
    })
}

export function fetchAvailableReviewers(query: string, signal?: AbortSignal): Promise<AvailableReviewersApi> {
    return apiJson<AvailableReviewersApi>(projectPath('signals/reports/available_reviewers/'), {
        query: { query: query || undefined },
        signal,
    })
}

export function fetchReportPullRequestChecks(
    reportId: string,
    pullRequestId: string,
    signal?: AbortSignal
): Promise<PullRequestChecksResponseApi> {
    return apiJson<PullRequestChecksResponseApi>(
        projectPath(`signals/reports/${encodeURIComponent(reportId)}/pr_checks/`),
        { query: { pull_request_id: pullRequestId }, signal }
    )
}
