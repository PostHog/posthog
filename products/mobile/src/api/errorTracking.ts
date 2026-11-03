import type {
    ErrorTrackingIssueListItemApi,
    ErrorTrackingIssuesListQueryRequestApi,
    ErrorTrackingIssuesListResponseApi,
} from '../../../error_tracking/frontend/generated/api.schemas'
import type { SignalsReportsListParams } from '../../../signals/frontend/generated/api.schemas'

import { apiJson, projectPath } from './client'
import { type InboxPageApi, type ProjectScope, scopeKey } from './reports'

// Shapes follow the serializers in `products/error_tracking/backend/presentation/views/`: `query_serializers.py` for
// the compact `error_tracking/query/` reads, `issues.py` for the issue resource and `spike_events.py`. Every endpoint
// here needs `error_tracking:read`, and the writes need `error_tracking:write`.

export type IssueStatusApi = 'active' | 'resolved' | 'suppressed' | 'archived' | 'pending_release'
export type WritableIssueStatus = 'active' | 'resolved' | 'suppressed'

/** `ErrorTrackingIssueAssigneeReadSerializer`: a user's numeric id, or a role's UUID. */
export interface IssueAssigneeApi {
    id?: number | string | null
    type?: 'user' | 'role' | string | null
}

/** `ErrorTrackingAggregationsSerializer`. Counts arrive as floats. */
export interface IssueAggregationsApi {
    occurrences?: number
    users?: number
    sessions?: number
    volumeRange?: number[]
}

export type IssueListItemApi = ErrorTrackingIssueListItemApi
export type IssuesListResponseApi = ErrorTrackingIssuesListResponseApi

export interface IssueReleaseApi {
    version?: string
    commit_id?: string
    branch?: string
}

export interface IssueTrendApi {
    direction: 'increasing' | 'decreasing' | 'stable' | 'new'
    change_percent?: number
}

export interface IssueSummaryApi extends IssueListItemApi {
    impact?: { occurrences?: number; users?: number; sessions?: number }
    trend?: IssueTrendApi
    sparkline?: number[]
    latest_release?: IssueReleaseApi
    first_release?: IssueReleaseApi
}

export interface BreakdownValueApi {
    value: string
    count: number
}

/** `ErrorTrackingIssueBreakdownSerializer`. A dimension with no values is left out of `top_values`. */
export interface IssueBreakdownApi {
    occurrences: number
    sample_session_ids: string[]
    top_values: Partial<
        Record<'path' | 'url' | 'screen' | 'browser' | 'os' | 'library' | 'app_version', BreakdownValueApi[]>
    >
}

export interface StackFrameApi {
    resolved_name?: string | null
    mangled_name?: string | null
    function?: string | null
    source?: string | null
    line?: number | null
    in_app?: boolean
}

export interface ExceptionApi {
    type?: string
    value?: string
    /** `same_as_event` replaces a stack the page already returned; the app reads frames from the first copy only. */
    stacktrace?: { frames?: StackFrameApi[] } | null
}

export interface IssueEventApi {
    uuid?: string
    timestamp?: string
    properties?: {
        $exception_list?: ExceptionApi[]
        $session_id?: string | null
        $browser?: string | null
        $os?: string | null
    }
}

export interface IssueEventsResponseApi {
    results: IssueEventApi[]
}

export interface IssueApi {
    id: string
    status: IssueStatusApi
    name: string | null
    description: string | null
    first_seen: string | null
    assignee: IssueAssigneeApi | null
}

export interface SpikeEventApi {
    issue: { id: string }
    detected_at: string
}

export interface SpikeEventsResponseApi {
    results: SpikeEventApi[]
}

export type ErrorsWindow = '24h' | '7d'

export const ISSUE_BUCKETS: Record<ErrorsWindow, number> = { '24h': 24, '7d': 28 }
export const ISSUES_PAGE_SIZE = 15
export const ISSUE_EVENTS_LIMIT = 10

export function windowDateRange(window: ErrorsWindow): { date_from: string } {
    return { date_from: window === '24h' ? '-24h' : '-7d' }
}

export interface IssuesListInput {
    window: ErrorsWindow
    assigneeUserId?: number
}

export function issuesListBody(
    { window, assigneeUserId }: IssuesListInput,
    offset = 0
): ErrorTrackingIssuesListQueryRequestApi {
    return {
        dateRange: windowDateRange(window),
        status: 'active',
        orderBy: 'users',
        orderDirection: 'DESC',
        limit: ISSUES_PAGE_SIZE,
        offset,
        volumeResolution: 0,
        ...(assigneeUserId === undefined ? {} : { assignee: { type: 'user', id: assigneeUserId } }),
    }
}

export function fetchIssues(input: IssuesListInput, signal?: AbortSignal, offset = 0): Promise<IssuesListResponseApi> {
    return apiJson<IssuesListResponseApi>(projectPath('error_tracking/query/issues/'), {
        method: 'POST',
        json: issuesListBody(input, offset),
        signal,
    })
}

export function fetchIssueSummary(
    issueId: string,
    window: ErrorsWindow,
    signal?: AbortSignal
): Promise<IssueSummaryApi> {
    return apiJson<IssueSummaryApi>(projectPath('error_tracking/query/issue/'), {
        method: 'POST',
        json: {
            issueId,
            dateRange: windowDateRange(window),
            includeSparkline: true,
            volumeResolution: ISSUE_BUCKETS[window],
        },
        signal,
    })
}

/**
 * The same endpoint with `includeBreakdown`, as its own request: the breakdown adds an aggregate query, and the server
 * fails the whole response when it cannot compute it, so it must not hold up or break the impact numbers.
 */
export async function fetchIssueBreakdown(
    issueId: string,
    window: ErrorsWindow,
    signal?: AbortSignal
): Promise<IssueBreakdownApi | null> {
    const summary = await apiJson<IssueSummaryApi & { breakdown?: IssueBreakdownApi }>(
        projectPath('error_tracking/query/issue/'),
        {
            method: 'POST',
            json: { issueId, dateRange: windowDateRange(window), includeBreakdown: true },
            signal,
        }
    )
    return summary.breakdown ?? null
}

export function fetchIssueEvents(
    issueId: string,
    window: ErrorsWindow,
    signal?: AbortSignal
): Promise<IssueEventsResponseApi> {
    return apiJson<IssueEventsResponseApi>(projectPath('error_tracking/query/issue_events/'), {
        method: 'POST',
        json: {
            issueId,
            dateRange: windowDateRange(window),
            limit: ISSUE_EVENTS_LIMIT,
            include: ['exception', 'stacktrace', 'environment', 'correlation'],
            onlyAppFrames: true,
        },
        signal,
    })
}

export function fetchIssue(issueId: string, signal?: AbortSignal): Promise<IssueApi> {
    return apiJson<IssueApi>(projectPath(`error_tracking/issues/${encodeURIComponent(issueId)}/`), { signal })
}

export function updateIssueStatus(issueId: string, status: WritableIssueStatus): Promise<IssueApi> {
    return apiJson<IssueApi>(projectPath(`error_tracking/issues/${encodeURIComponent(issueId)}/`), {
        method: 'PATCH',
        json: { status },
    })
}

/** `null` removes the assignment. */
export async function assignIssue(issueId: string, userId: number | null): Promise<void> {
    await apiJson<unknown>(projectPath(`error_tracking/issues/${encodeURIComponent(issueId)}/assign/`), {
        method: 'PATCH',
        json: { assignee: userId === null ? null : { type: 'user', id: userId } },
    })
}

export const SPIKE_EVENTS_LIMIT = 100

export function fetchSpikeEvents(
    issueIds: readonly string[],
    dateFrom: string,
    signal?: AbortSignal
): Promise<SpikeEventsResponseApi> {
    return apiJson<SpikeEventsResponseApi>(projectPath('error_tracking/spike_events/'), {
        query: { issue_ids: issueIds.join(','), date_from: dateFrom, limit: SPIKE_EVENTS_LIMIT },
        signal,
    })
}

/**
 * `GET signals/reports/` narrowed to reports built from this issue's signals: error tracking signals carry the issue
 * id as their `source_id`. Needs `task:read`, which the inbox already uses.
 */
export function fetchIssueReports(issueId: string, signal?: AbortSignal): Promise<InboxPageApi> {
    return apiJson<InboxPageApi>(projectPath('signals/reports/'), {
        query: {
            source_product: 'error_tracking',
            source_id: issueId,
            limit: 1,
            include_source_metadata: false,
        } satisfies SignalsReportsListParams,
        signal,
    })
}

/** Query keys. Every key carries the host and project so a project switch never shows stale data. */
export const errorTrackingKeys = {
    all: (scope: ProjectScope | null) => ['error_tracking', ...scopeKey(scope)] as const,
    lists: (scope: ProjectScope | null) => [...errorTrackingKeys.all(scope), 'issues'] as const,
    list: (scope: ProjectScope | null, input: IssuesListInput) =>
        [...errorTrackingKeys.lists(scope), input.window, input.assigneeUserId ?? null, 'pages'] as const,
    spikes: (scope: ProjectScope | null, window: ErrorsWindow, issueIds: readonly string[]) =>
        [...errorTrackingKeys.all(scope), 'spikes', window, issueIds.join(',')] as const,
    issueAll: (scope: ProjectScope | null, issueId: string) =>
        [...errorTrackingKeys.all(scope), 'issue', issueId] as const,
    issue: (scope: ProjectScope | null, issueId: string) =>
        [...errorTrackingKeys.issueAll(scope, issueId), 'detail'] as const,
    summary: (scope: ProjectScope | null, issueId: string, window: ErrorsWindow) =>
        [...errorTrackingKeys.issueAll(scope, issueId), 'summary', window] as const,
    breakdown: (scope: ProjectScope | null, issueId: string, window: ErrorsWindow) =>
        [...errorTrackingKeys.issueAll(scope, issueId), 'breakdown', window] as const,
    events: (scope: ProjectScope | null, issueId: string, window: ErrorsWindow) =>
        [...errorTrackingKeys.issueAll(scope, issueId), 'events', window] as const,
    reports: (scope: ProjectScope | null, issueId: string) =>
        [...errorTrackingKeys.issueAll(scope, issueId), 'reports'] as const,
}
