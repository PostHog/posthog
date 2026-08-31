import {
    MakeLogicType,
    LogicWrapper,
    actions,
    afterMount,
    connect,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { ApiConfig, ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { groupBy } from 'lib/utils/arrays'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import {
    engineeringAnalyticsCiCards,
    engineeringAnalyticsPullRequests,
    engineeringAnalyticsQuarantine,
    engineeringAnalyticsSources,
    engineeringAnalyticsTrunkQuarantine,
    engineeringAnalyticsWorkflowHealth,
} from '../generated/api'
import type { GitHubSourceApi, PullRequestListItemApi, PushCISampleApi } from '../generated/api.schemas'
import { CIStatus, ciStatusOf } from '../lib/ci'
import { type FleetSummary, computeFleetSummary } from '../lib/runHealth'
import { scopeToValue } from '../lib/scope'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import type { BranchHealthParams } from './engineeringAnalyticsFiltersLogic'

// Mirrors the endpoint's server-side limit.
export const PR_TABLE_LIMIT = 1000

// Mirrors `workflow_health.py` `_LIMIT` (top workflows by run count).
export const WORKFLOW_HEALTH_LIMIT = 100

const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export type PRState = 'open' | 'closed' | 'merged'
/** 'draft' narrows open PRs; the other values mirror PRState. */
export type PRStateFilter = PRState | 'draft' | 'all'
export type CIStatusFilter = CIStatus | 'all'
export type CardFilter = 'open' | 'failing' | 'stuck' | 'ready' | 'thrash'

/** Mirrors the ci_cards "stuck" rule: open, non-draft, non-bot, older than 7 days. */
export const STUCK_AFTER_DAYS = 7

export interface PullRequestRow {
    number: number
    title: string
    repoOwner: string
    repoName: string
    authorHandle: string
    authorAvatarUrl: string
    isBot: boolean
    state: PRState
    isDraft: boolean
    createdAt: string
    mergedAt: string | null
    /** Coarse: created_at → merged_at. This is open-to-merge, never review/cycle time. Merged PRs only. */
    openToMergeSeconds: number | null
    labels: string[]
    runs: number
    passing: number
    failing: number
    pending: number
    /** Workflow names behind `failing`, sorted. */
    failingWorkflows: string[]
    /** Distinct head SHAs across the PR's workflow runs. Fork PRs unattributed. */
    pushes: number
    /** Per-push CI rounds oldest first, capped server-side — drives the push-history sparkline. */
    pushHistory: PushCISampleApi[]
    /** Workflow runs attributed to this PR that were a 2nd+ attempt. */
    rerunCycles: number
    /** Estimated CI cost (USD) over the PR's billable jobs. Null when the job source isn't synced. */
    estimatedCostUsd: number | null
    /** Billable (self-hosted) minutes over the PR's jobs. Null when the job source isn't synced. */
    billableMinutes: number | null
}

export interface CardsData {
    openPrs: number
    repos: number
    stuck: number
    failingCi: number
}

/** Bucket width of a workflow's history series, picked by the server from the window length. */
export type WorkflowGranularity = 'hour' | 'day' | 'week'

export interface WorkflowHealthBucket {
    /** Bucket start (ISO), aligned to the granularity (top of hour / midnight / Monday). */
    bucketStart: string
    runCount: number
    completed: number
    successes: number
    /** Decisive failures only (failure / timed_out); excludes skipped, cancelled, action_required. */
    failures: number
}

export interface WorkflowHealthRow {
    repoOwner: string
    repoName: string
    workflowName: string
    runCount: number
    /** Over completed runs only; null when nothing has settled yet. */
    successRate: number | null
    p50Seconds: number | null
    p95Seconds: number | null
    lastFailureAt: string | null
    /** Most recent completed run was a decisive failure; null when nothing has completed. Drives OK/RED. */
    latestRunFailed: boolean | null
    /** Raw conclusion of the most recent completed run (success / cancelled / skipped / …); null if none. */
    latestRunConclusion: string | null
    /** Bucket width of `buckets`: 'hour', 'day', or 'week'. */
    granularity: WorkflowGranularity
    /** Zero-filled across the whole window, oldest first. */
    buckets: WorkflowHealthBucket[]
    /** Billable CI minutes for this workflow within the scope; undefined when no cost data is loaded. */
    billableMinutes?: number | null
    /** Estimated $ cost for this workflow within the scope; null when nothing was costable. */
    estimatedCostUsd?: number | null
    /** Runs in the window that were a 2nd+ attempt. */
    rerunCycles?: number
    /** Success rate over the previous equal-length window. */
    successRatePrev?: number | null
}

export interface WorkflowFailureSeries {
    completed: number[]
    failures: number[]
    labels: string[]
}

/** Bucket label per the shared series granularity, for chart tooltips. */
export function formatBucket(bucketStart: string, granularity: WorkflowGranularity): string {
    // Buckets are computed server-side on UTC boundaries, so the label must read them in UTC too —
    // parsing in the browser's local timezone can shift a midnight bucket to the wrong day.
    const at = dayjs.utc(bucketStart)
    if (granularity === 'hour') {
        return at.format('MMM D, HH:mm')
    }
    if (granularity === 'week') {
        return `Week of ${at.format('MMM D')}`
    }
    return at.format('MMM D')
}

/** Stacked sparkline series: bar height = completed runs, red portion = decisive failures. */
export function workflowFailureSeries(
    buckets: WorkflowHealthBucket[],
    granularity: WorkflowGranularity
): WorkflowFailureSeries {
    const completed = buckets.map((b) => b.completed)
    const failures = buckets.map((b) => b.failures)
    const labels = buckets.map((b) => {
        const when = formatBucket(b.bucketStart, granularity)
        return b.completed > 0 ? `${when} · ${b.failures} of ${b.completed} failed` : `${when} · no completed runs`
    })
    return { completed, failures, labels }
}

/** 'failing'/'passing' key off the latest settled run; rows with nothing completed show only under 'all'. */
export type WorkflowStatusFilter = 'all' | 'failing' | 'passing'

export interface WorkflowFilters {
    search: string
    status: WorkflowStatusFilter
}

export const DEFAULT_WORKFLOW_FILTERS: WorkflowFilters = { search: '', status: 'all' }

export function filterWorkflowHealth(rows: WorkflowHealthRow[], filters: WorkflowFilters): WorkflowHealthRow[] {
    const search = filters.search.trim().toLowerCase()
    return rows.filter((row) => {
        if (filters.status === 'failing' && row.latestRunFailed !== true) {
            return false
        }
        if (filters.status === 'passing' && row.latestRunFailed !== false) {
            return false
        }
        return !search || row.workflowName.toLowerCase().includes(search)
    })
}

export function prKeyOf(row: Pick<PullRequestRow, 'repoOwner' | 'repoName' | 'number'>): string {
    return `${row.repoOwner}/${row.repoName}#${row.number}`
}

/** ?? fallbacks: a new frontend can briefly hit an older backend predating the cost/push fields. */
export function toPullRequestRow(it: PullRequestListItemApi): PullRequestRow {
    return {
        number: it.number,
        title: it.title,
        repoOwner: it.repo.owner,
        repoName: it.repo.name,
        authorHandle: it.author.handle,
        authorAvatarUrl: it.author.avatar_url,
        isBot: it.author.is_bot,
        state: it.state as PRState,
        isDraft: it.is_draft,
        createdAt: it.created_at,
        mergedAt: it.merged_at,
        openToMergeSeconds: it.open_to_merge_seconds,
        labels: it.labels,
        runs: it.ci.runs,
        passing: it.ci.passing,
        failing: it.ci.failing,
        pending: it.ci.pending,
        failingWorkflows: it.ci.failing_workflows ?? [],
        pushes: it.pushes ?? 0,
        pushHistory: it.push_history ?? [],
        rerunCycles: it.rerun_cycles ?? 0,
        estimatedCostUsd: it.estimated_cost_usd ?? null,
        billableMinutes: it.billable_minutes ?? null,
    }
}

export interface PullRequestFilters {
    state: PRStateFilter
    author: string | null
    repo: string | null
    ciStatus: CIStatusFilter
    search: string
    stuckOnly: boolean
    readyOnly: boolean
    thrashOnly: boolean
}

export const DEFAULT_FILTERS: PullRequestFilters = {
    state: 'open',
    author: null,
    repo: null,
    ciStatus: 'all',
    search: '',
    stuckOnly: false,
    readyOnly: false,
    thrashOnly: false,
}

export function isStuck(row: PullRequestRow, stuckCutoffMs: number): boolean {
    return row.state === 'open' && !row.isDraft && !row.isBot && Date.parse(row.createdAt) < stuckCutoffMs
}

/** Open, ready-for-review, and green — the "unblocked, could merge" pile. */
export function isReady(row: PullRequestRow): boolean {
    return row.state === 'open' && !row.isDraft && ciStatusOf(row) === 'passing'
}

/** Open and burning re-run cycles — CI thrash worth a look. */
export function isThrashing(row: PullRequestRow): boolean {
    return row.state === 'open' && row.rerunCycles > 0
}

function matchesStateFilter(row: PullRequestRow, state: PRStateFilter): boolean {
    if (state === 'all') {
        return true
    }
    if (state === 'draft') {
        return row.state === 'open' && row.isDraft
    }
    return row.state === state
}

export function filterPullRequests(
    rows: PullRequestRow[],
    filters: PullRequestFilters,
    now: dayjs.Dayjs = dayjs()
): PullRequestRow[] {
    const search = filters.search.trim().toLowerCase()
    // Hoisted: re-runs per keystroke over up to 1000 rows — no dayjs allocation in the row loop.
    const stuckCutoffMs = filters.stuckOnly ? now.subtract(STUCK_AFTER_DAYS, 'day').valueOf() : 0
    return rows.filter((row) => {
        if (!matchesStateFilter(row, filters.state)) {
            return false
        }
        if (filters.stuckOnly && !isStuck(row, stuckCutoffMs)) {
            return false
        }
        if (filters.readyOnly && !isReady(row)) {
            return false
        }
        if (filters.thrashOnly && !isThrashing(row)) {
            return false
        }
        if (filters.author && row.authorHandle !== filters.author) {
            return false
        }
        if (filters.repo && `${row.repoOwner}/${row.repoName}` !== filters.repo) {
            return false
        }
        if (filters.ciStatus !== 'all' && ciStatusOf(row) !== filters.ciStatus) {
            return false
        }
        if (search) {
            const haystack =
                `${row.title} ${row.repoOwner}/${row.repoName} ${row.authorHandle} #${row.number}`.toLowerCase()
            if (!haystack.includes(search)) {
                return false
            }
        }
        return true
    })
}

export type QuarantineMode = 'run' | 'skip'
export type QuarantineLifecycle = 'active' | 'expiring_soon' | 'in_grace' | 'overdue'
export type QuarantineSelectorKind = 'product' | 'directory' | 'file' | 'test'

export interface QuarantineEntryRow {
    id: string
    runner: string
    reason: string
    owner: string
    /** Tracking issue URL, or '' when none was filed. */
    issue: string
    /** ISO date. */
    added: string
    /** ISO date. */
    expires: string
    mode: QuarantineMode
    lifecycle: QuarantineLifecycle
    /** Negative once past expiry. */
    daysUntilExpiry: number
    selectorKind: QuarantineSelectorKind
}

export interface QuarantineData {
    available: boolean
    entries: QuarantineEntryRow[]
    parseErrors: string[]
    parseWarnings: string[]
    sourceUrl: string
    /** owner/name, or null when read from the local checkout in dev. */
    repoFullName: string | null
}

export interface TrunkQuarantinedTestRow {
    runner: string
    nodeid: string
    file: string
    ownerTeam: string
    status: string
    quarantineSetting: string
    quarantinedAt: string
    ageDays: number
    overdue: boolean
    /** The Trunk app's page for this test; null when the source has no org slug or the row no id. */
    trunkUrl: string | null
}

export interface TrunkQuarantineTeamRow {
    ownerTeam: string
    testCount: number
    overdueCount: number
    oldestAgeDays: number
}

export interface TrunkQuarantineData {
    /** False when no TrunkIo source has the QuarantinedTests endpoint synced; not an error. */
    available: boolean
    ttlDays: number
    /** 'owner/name' the debt was read for; test file paths are relative to it. */
    repository: string
    /** The Trunk app's flaky-tests page for this repository; null when the source has no org slug. */
    trunkUrl: string | null
    teams: TrunkQuarantineTeamRow[]
    tests: TrunkQuarantinedTestRow[]
}

/**
 * Per-loader outcome. A 400 means "no GitHub source" for every scene; any other failure stays scoped
 * to the loader that hit it, so a 500 on one endpoint doesn't error a scene that doesn't read it.
 */
export type LoaderStatus = 'ok' | 'notConnected' | 'error'

export function loaderStatusFromError(errorObject: unknown): LoaderStatus {
    return errorObject instanceof ApiError && errorObject.status === 400 ? 'notConnected' : 'error'
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface engineeringAnalyticsLogicValues {
    branchHealthParams: BranchHealthParams // engineeringAnalyticsFiltersLogic
    dateFrom: string | null // engineeringAnalyticsFiltersLogic
    dateTo: string | null // engineeringAnalyticsFiltersLogic
    activeCard: CardFilter | null
    activeSource: GitHubSourceApi | null
    anyLoading: boolean
    author: string | null
    cards: CardsData | null
    cardsLoading: boolean
    cardsStatus: LoaderStatus
    ciStatusFilter: CIStatusFilter
    expandedTrunkQuarantineTeams: string[]
    filteredPullRequests: PullRequestRow[]
    filteredWorkflowHealth: WorkflowHealthRow[]
    filters: PullRequestFilters
    fleetSummary: FleetSummary
    fleetTruncated: boolean
    githubSources: GitHubSourceApi[]
    githubSourcesLoading: boolean
    hasActiveFilters: boolean
    hasActiveWorkflowFilters: boolean
    hasMultipleSources: boolean
    notConnected: boolean
    pullRequests: PullRequestRow[]
    pullRequestsLoadError: boolean
    pullRequestsLoading: boolean
    pullRequestsStatus: LoaderStatus
    quarantine: QuarantineData | null
    quarantineLoadFailed: boolean
    quarantineLoading: boolean
    readyCount: number
    readyOnly: boolean
    repo: string | null
    scopeRepo: string | null
    search: string
    selectedScope: string | null
    sourceId: string | null
    sourceOptions: {
        label: string
        value: string
    }[]
    stateFilter: PRStateFilter
    stuckOnly: boolean
    tableTruncated: boolean
    thrashCount: number
    thrashOnly: boolean
    trunkQuarantine: TrunkQuarantineData | null
    trunkQuarantineLoading: boolean
    trunkQuarantineStatus: LoaderStatus
    trunkQuarantineTestsByTeam: Record<string, TrunkQuarantinedTestRow[]>
    workflowCostAvailable: boolean
    workflowFilters: WorkflowFilters
    workflowHealth: WorkflowHealthRow[]
    workflowHealthLoadError: boolean
    workflowHealthLoading: boolean
    workflowHealthStatus: LoaderStatus
    workflowSearch: string
    workflowStatusFilter: WorkflowStatusFilter
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface engineeringAnalyticsLogicActions {
    applyCardFilter: (card: CardFilter) => {
        card: CardFilter
    }
    loadCards: () => any
    loadCardsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCardsSuccess: (
        cards: CardsData,
        payload?: any
    ) => {
        cards: CardsData
        payload?: any
    }
    loadGithubSources: () => any
    loadGithubSourcesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadGithubSourcesSuccess: (
        githubSources: GitHubSourceApi[],
        payload?: any
    ) => {
        githubSources: GitHubSourceApi[]
        payload?: any
    }
    loadPullRequests: () => any
    loadPullRequestsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPullRequestsSuccess: (
        pullRequests: PullRequestRow[],
        payload?: any
    ) => {
        pullRequests: PullRequestRow[]
        payload?: any
    }
    loadQuarantine: () => any
    loadQuarantineFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadQuarantineSuccess: (
        quarantine: QuarantineData,
        payload?: any
    ) => {
        quarantine: QuarantineData
        payload?: any
    }
    loadTrunkQuarantine: () => any
    loadTrunkQuarantineFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTrunkQuarantineSuccess: (
        trunkQuarantine: TrunkQuarantineData,
        payload?: any
    ) => {
        trunkQuarantine: TrunkQuarantineData
        payload?: any
    }
    loadWorkflowHealth: () => any
    loadWorkflowHealthFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadWorkflowHealthSuccess: (
        workflowHealth: WorkflowHealthRow[],
        payload?: any
    ) => {
        workflowHealth: WorkflowHealthRow[]
        payload?: any
    }
    refresh: () => {
        value: true
    }
    resetFilters: () => {
        value: true
    }
    resetWorkflowFilters: () => {
        value: true
    }
    setAuthor: (author: string | null) => {
        author: string | null
    }
    setCiStatusFilter: (ciStatus: CIStatusFilter) => {
        ciStatus: CIStatusFilter
    }
    setReadyOnly: (ready: boolean) => {
        ready: boolean
    }
    setRepo: (repo: string | null) => {
        repo: string | null
    }
    setScope: (
        sourceId: string | null,
        scopeRepo: string | null
    ) => {
        scopeRepo: string | null
        sourceId: string | null
    }
    setSearch: (search: string) => {
        search: string
    }
    setSourceId: (sourceId: string | null) => {
        sourceId: string | null
    }
    setStateFilter: (state: PRStateFilter) => {
        state: PRStateFilter
    }
    setStuckOnly: (stuckOnly: boolean) => {
        stuckOnly: boolean
    }
    setThrashOnly: (thrash: boolean) => {
        thrash: boolean
    }
    setWorkflowSearch: (search: string) => {
        search: string
    }
    setWorkflowStatusFilter: (status: WorkflowStatusFilter) => {
        status: WorkflowStatusFilter
    }
    toggleTrunkQuarantineTeam: (team: string) => {
        team: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface engineeringAnalyticsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        fleetSummary: (workflowHealth: WorkflowHealthRow[]) => FleetSummary
        fleetTruncated: (workflowHealth: WorkflowHealthRow[]) => boolean
        workflowFilters: (workflowSearch: string, workflowStatusFilter: WorkflowStatusFilter) => WorkflowFilters
        filteredWorkflowHealth: (
            workflowHealth: WorkflowHealthRow[],
            workflowFilters: WorkflowFilters
        ) => WorkflowHealthRow[]
        hasActiveWorkflowFilters: (workflowFilters: WorkflowFilters) => boolean
        workflowCostAvailable: (workflowHealth: WorkflowHealthRow[]) => boolean
        filters: (
            stateFilter: PRStateFilter,
            author: string | null,
            repo: string | null,
            ciStatusFilter: CIStatusFilter,
            search: string,
            stuckOnly: boolean,
            readyOnly: boolean,
            thrashOnly: boolean
        ) => PullRequestFilters
        activeCard: (
            stateFilter: PRStateFilter,
            ciStatusFilter: CIStatusFilter,
            stuckOnly: boolean,
            readyOnly: boolean,
            thrashOnly: boolean
        ) => CardFilter | null
        filteredPullRequests: (pullRequests: PullRequestRow[], filters: PullRequestFilters) => PullRequestRow[]
        hasActiveFilters: (filters: PullRequestFilters) => boolean
        readyCount: (pullRequests: PullRequestRow[]) => number
        thrashCount: (pullRequests: PullRequestRow[]) => number
        anyLoading: (
            cardsLoading: boolean,
            pullRequestsLoading: boolean,
            workflowHealthLoading: boolean,
            quarantineLoading: boolean
        ) => boolean
        notConnected: (
            cardsStatus: LoaderStatus,
            pullRequestsStatus: LoaderStatus,
            workflowHealthStatus: LoaderStatus
        ) => boolean
        pullRequestsLoadError: (cardsStatus: LoaderStatus, pullRequestsStatus: LoaderStatus) => boolean
        workflowHealthLoadError: (workflowHealthStatus: LoaderStatus) => boolean
        tableTruncated: (pullRequests: PullRequestRow[]) => boolean
        trunkQuarantineTestsByTeam: (
            trunkQuarantine: TrunkQuarantineData | null
        ) => Record<string, TrunkQuarantinedTestRow[]>
        hasMultipleSources: (githubSources: GitHubSourceApi[]) => boolean
        activeSource: (
            githubSources: GitHubSourceApi[],
            sourceId: string | null,
            scopeRepo: string | null
        ) => GitHubSourceApi | null
        sourceOptions: (githubSources: GitHubSourceApi[]) => {
            label: string
            value: string
        }[]
        selectedScope: (
            githubSources: GitHubSourceApi[],
            sourceId: string | null,
            scopeRepo: string | null
        ) => string | null
    }
}

export type engineeringAnalyticsLogicType = MakeLogicType<
    engineeringAnalyticsLogicValues,
    engineeringAnalyticsLogicActions,
    Record<string, any>,
    engineeringAnalyticsLogicMeta
>

export const engineeringAnalyticsLogic: LogicWrapper<engineeringAnalyticsLogicType> =
    kea<engineeringAnalyticsLogicType>([
        path(['products', 'engineering_analytics', 'frontend', 'scenes', 'engineeringAnalyticsLogic']),

        connect(() => ({
            values: [engineeringAnalyticsFiltersLogic, ['dateFrom', 'dateTo', 'branchHealthParams']],
        })),

        actions({
            setStateFilter: (state: PRStateFilter) => ({ state }),
            setAuthor: (author: string | null) => ({ author }),
            setRepo: (repo: string | null) => ({ repo }),
            setCiStatusFilter: (ciStatus: CIStatusFilter) => ({ ciStatus }),
            setSearch: (search: string) => ({ search }),
            setWorkflowSearch: (search: string) => ({ search }),
            setWorkflowStatusFilter: (status: WorkflowStatusFilter) => ({ status }),
            resetWorkflowFilters: true,
            setStuckOnly: (stuckOnly: boolean) => ({ stuckOnly }),
            setReadyOnly: (ready: boolean) => ({ ready }),
            setThrashOnly: (thrash: boolean) => ({ thrash }),
            applyCardFilter: (card: CardFilter) => ({ card }),
            setSourceId: (sourceId: string | null) => ({ sourceId }),
            // The picker selects a (source, repo) pair in one action, so both land before a single refresh.
            setScope: (sourceId: string | null, scopeRepo: string | null) => ({ sourceId, scopeRepo }),
            resetFilters: true,
            toggleTrunkQuarantineTeam: (team: string) => ({ team }),
            refresh: true,
        }),

        loaders(({ values }) => ({
            cards: [
                null as CardsData | null,
                {
                    loadCards: async (): Promise<CardsData> => {
                        const data = await engineeringAnalyticsCiCards(projectId(), {
                            source_id: values.sourceId ?? undefined,
                            repo: values.scopeRepo ?? undefined,
                        })
                        return {
                            openPrs: data.open_prs,
                            repos: data.repos,
                            stuck: data.stuck,
                            failingCi: data.failing_ci,
                        }
                    },
                },
            ],
            pullRequests: [
                [] as PullRequestRow[],
                {
                    loadPullRequests: async (): Promise<PullRequestRow[]> => {
                        const response = await engineeringAnalyticsPullRequests(projectId(), {
                            source_id: values.sourceId ?? undefined,
                            repo: values.scopeRepo ?? undefined,
                        })
                        return response.items.map(toPullRequestRow)
                    },
                },
            ],
            workflowHealth: [
                [] as WorkflowHealthRow[],
                {
                    loadWorkflowHealth: async (): Promise<WorkflowHealthRow[]> => {
                        const items = await engineeringAnalyticsWorkflowHealth(projectId(), {
                            date_from: values.dateFrom ?? undefined,
                            date_to: values.dateTo ?? undefined,
                            ...values.branchHealthParams,
                            source_id: values.sourceId ?? undefined,
                            repo: values.scopeRepo ?? undefined,
                        })
                        return items.map(
                            (it): WorkflowHealthRow => ({
                                repoOwner: it.repo.owner,
                                repoName: it.repo.name,
                                workflowName: it.workflow_name,
                                runCount: it.run_count,
                                successRate: it.success_rate,
                                p50Seconds: it.p50_seconds,
                                p95Seconds: it.p95_seconds,
                                lastFailureAt: it.last_failure_at,
                                // ?? fallbacks: a new frontend can briefly hit an older backend predating these fields.
                                latestRunFailed: it.latest_run_failed ?? null,
                                latestRunConclusion: it.latest_run_conclusion ?? null,
                                granularity: (it.granularity ?? 'day') as WorkflowGranularity,
                                buckets: (it.buckets ?? []).map((b) => ({
                                    bucketStart: b.bucket_start,
                                    runCount: b.run_count,
                                    completed: b.completed,
                                    successes: b.successes,
                                    failures: b.failures ?? 0,
                                })),
                                billableMinutes: it.billable_minutes ?? null,
                                estimatedCostUsd: it.estimated_cost_usd ?? null,
                                rerunCycles: it.rerun_cycles ?? 0,
                                successRatePrev: it.success_rate_prev ?? null,
                            })
                        )
                    },
                },
            ],
            quarantine: [
                null as QuarantineData | null,
                {
                    loadQuarantine: async (): Promise<QuarantineData> => {
                        const data = await engineeringAnalyticsQuarantine(projectId(), {
                            source_id: values.sourceId ?? undefined,
                            repo: values.scopeRepo ?? undefined,
                        })
                        return {
                            available: data.available,
                            entries: data.entries.map(
                                (it): QuarantineEntryRow => ({
                                    id: it.id,
                                    runner: it.runner,
                                    reason: it.reason,
                                    owner: it.owner,
                                    issue: it.issue,
                                    added: it.added,
                                    expires: it.expires,
                                    mode: it.mode as QuarantineMode,
                                    lifecycle: it.lifecycle as QuarantineLifecycle,
                                    daysUntilExpiry: it.days_until_expiry,
                                    selectorKind: it.selector_kind as QuarantineSelectorKind,
                                })
                            ),
                            parseErrors: data.parse_errors,
                            parseWarnings: data.parse_warnings,
                            sourceUrl: data.source_url,
                            repoFullName: data.repo ? `${data.repo.owner}/${data.repo.name}` : null,
                        }
                    },
                },
            ],
            trunkQuarantine: [
                null as TrunkQuarantineData | null,
                {
                    loadTrunkQuarantine: async (): Promise<TrunkQuarantineData> => {
                        const data = await engineeringAnalyticsTrunkQuarantine(projectId(), {
                            source_id: values.sourceId ?? undefined,
                            repo: values.scopeRepo ?? undefined,
                        })
                        return {
                            available: data.available,
                            ttlDays: data.ttl_days,
                            repository: data.repository,
                            trunkUrl: data.trunk_url ?? null,
                            teams: data.teams.map(
                                (it): TrunkQuarantineTeamRow => ({
                                    ownerTeam: it.owner_team,
                                    testCount: it.test_count,
                                    overdueCount: it.overdue_count,
                                    oldestAgeDays: it.oldest_age_days,
                                })
                            ),
                            tests: data.tests.map(
                                (it): TrunkQuarantinedTestRow => ({
                                    runner: it.runner,
                                    nodeid: it.nodeid,
                                    file: it.file,
                                    ownerTeam: it.owner_team,
                                    status: it.status,
                                    quarantineSetting: it.quarantine_setting,
                                    quarantinedAt: it.quarantined_at,
                                    ageDays: it.age_days,
                                    overdue: it.overdue,
                                    trunkUrl: it.trunk_url ?? null,
                                })
                            ),
                        }
                    },
                },
            ],
            githubSources: [
                [] as GitHubSourceApi[],
                {
                    loadGithubSources: async (): Promise<GitHubSourceApi[]> =>
                        await engineeringAnalyticsSources(projectId()),
                },
            ],
        })),

        reducers({
            stateFilter: [
                DEFAULT_FILTERS.state,
                { setStateFilter: (_, { state }) => state, resetFilters: () => DEFAULT_FILTERS.state },
            ],
            author: [
                DEFAULT_FILTERS.author,
                { setAuthor: (_, { author }) => author, resetFilters: () => DEFAULT_FILTERS.author },
            ],
            repo: [DEFAULT_FILTERS.repo, { setRepo: (_, { repo }) => repo, resetFilters: () => DEFAULT_FILTERS.repo }],
            ciStatusFilter: [
                DEFAULT_FILTERS.ciStatus,
                { setCiStatusFilter: (_, { ciStatus }) => ciStatus, resetFilters: () => DEFAULT_FILTERS.ciStatus },
            ],
            search: [
                DEFAULT_FILTERS.search,
                { setSearch: (_, { search }) => search, resetFilters: () => DEFAULT_FILTERS.search },
            ],
            // Changing the state filter exits stuck-only — stuck implies open.
            stuckOnly: [
                DEFAULT_FILTERS.stuckOnly,
                {
                    setStuckOnly: (_, { stuckOnly }) => stuckOnly,
                    setStateFilter: () => false,
                    resetFilters: () => DEFAULT_FILTERS.stuckOnly,
                },
            ],
            readyOnly: [
                DEFAULT_FILTERS.readyOnly,
                {
                    setReadyOnly: (_, { ready }) => ready,
                    setStateFilter: () => false,
                    resetFilters: () => DEFAULT_FILTERS.readyOnly,
                },
            ],
            thrashOnly: [
                DEFAULT_FILTERS.thrashOnly,
                {
                    setThrashOnly: (_, { thrash }) => thrash,
                    setStateFilter: () => false,
                    resetFilters: () => DEFAULT_FILTERS.thrashOnly,
                },
            ],
            workflowSearch: [
                DEFAULT_WORKFLOW_FILTERS.search,
                {
                    setWorkflowSearch: (_, { search }) => search,
                    resetWorkflowFilters: () => DEFAULT_WORKFLOW_FILTERS.search,
                },
            ],
            workflowStatusFilter: [
                DEFAULT_WORKFLOW_FILTERS.status,
                {
                    setWorkflowStatusFilter: (_, { status }) => status,
                    resetWorkflowFilters: () => DEFAULT_WORKFLOW_FILTERS.status,
                },
            ],
            // Which GitHub source to read; null = backend default (oldest connected). Synced to `?source=`.
            sourceId: [
                null as string | null,
                { setSourceId: (_, { sourceId }) => sourceId, setScope: (_, { sourceId }) => sourceId },
            ],
            // Repo scope of a multi-repo source. Cleared when the source changes on its own (the old repo
            // belongs to the old source); the picker uses setScope to set both together.
            scopeRepo: [null as string | null, { setScope: (_, { scopeRepo }) => scopeRepo, setSourceId: () => null }],
            cardsStatus: [
                'ok' as LoaderStatus,
                {
                    loadCards: () => 'ok',
                    loadCardsSuccess: () => 'ok',
                    loadCardsFailure: (_, { errorObject }) => loaderStatusFromError(errorObject),
                },
            ],
            // The quarantine endpoint only 400s when there's no GitHub source and no local checkout.
            quarantineLoadFailed: [
                false,
                {
                    loadQuarantine: () => false,
                    loadQuarantineSuccess: () => false,
                    loadQuarantineFailure: () => true,
                },
            ],
            // Whole-row click toggles a team's slice open (controlled LemonTable expansion, like the
            // workflow runs table); a scope switch loads different teams, so open rows reset with it.
            expandedTrunkQuarantineTeams: [
                [] as string[],
                {
                    toggleTrunkQuarantineTeam: (state, { team }) =>
                        state.includes(team) ? state.filter((open) => open !== team) : [...state, team],
                    setSourceId: () => [],
                    setScope: () => [],
                },
            ],
            // Same tri-state as the other loaders: 'notConnected' (no source) defers to the tab-level
            // "connect a source" gate; only a real 'error' surfaces the board's own banner.
            trunkQuarantineStatus: [
                'ok' as LoaderStatus,
                {
                    loadTrunkQuarantine: () => 'ok',
                    loadTrunkQuarantineSuccess: () => 'ok',
                    loadTrunkQuarantineFailure: (_, { errorObject }) => loaderStatusFromError(errorObject),
                },
            ],
            pullRequestsStatus: [
                'ok' as LoaderStatus,
                {
                    loadPullRequests: () => 'ok',
                    loadPullRequestsSuccess: () => 'ok',
                    loadPullRequestsFailure: (_, { errorObject }) => loaderStatusFromError(errorObject),
                },
            ],
            workflowHealthStatus: [
                'ok' as LoaderStatus,
                {
                    loadWorkflowHealth: () => 'ok',
                    loadWorkflowHealthSuccess: () => 'ok',
                    loadWorkflowHealthFailure: (_, { errorObject }) => loaderStatusFromError(errorObject),
                },
            ],
        }),

        selectors({
            fleetSummary: [
                (s) => [s.workflowHealth],
                (workflowHealth: WorkflowHealthRow[]): FleetSummary => computeFleetSummary(workflowHealth),
            ],
            fleetTruncated: [
                (s) => [s.workflowHealth],
                (workflowHealth: WorkflowHealthRow[]): boolean => workflowHealth.length >= WORKFLOW_HEALTH_LIMIT,
            ],
            workflowFilters: [
                (s) => [s.workflowSearch, s.workflowStatusFilter],
                (search: string, status: WorkflowStatusFilter): WorkflowFilters => ({ search, status }),
            ],
            filteredWorkflowHealth: [
                (s) => [s.workflowHealth, s.workflowFilters],
                (workflowHealth: WorkflowHealthRow[], workflowFilters: WorkflowFilters): WorkflowHealthRow[] =>
                    filterWorkflowHealth(workflowHealth, workflowFilters),
            ],
            hasActiveWorkflowFilters: [
                (s) => [s.workflowFilters],
                (workflowFilters: WorkflowFilters): boolean =>
                    !objectsEqual(
                        { ...workflowFilters, search: workflowFilters.search.trim() },
                        DEFAULT_WORKFLOW_FILTERS
                    ),
            ],
            // Until the job-level source syncs every cost field is null — scenes hide the column instead.
            workflowCostAvailable: [
                (s) => [s.workflowHealth],
                (workflowHealth: WorkflowHealthRow[]): boolean =>
                    workflowHealth.some((row) => row.billableMinutes != null || row.estimatedCostUsd != null),
            ],
            filters: [
                (s) => [
                    s.stateFilter,
                    s.author,
                    s.repo,
                    s.ciStatusFilter,
                    s.search,
                    s.stuckOnly,
                    s.readyOnly,
                    s.thrashOnly,
                ],
                (
                    stateFilter: PRStateFilter,
                    author: string | null,
                    repo: string | null,
                    ciStatus: CIStatusFilter,
                    search: string,
                    stuckOnly: boolean,
                    readyOnly: boolean,
                    thrashOnly: boolean
                ): PullRequestFilters => ({
                    state: stateFilter,
                    author,
                    repo,
                    ciStatus,
                    search,
                    stuckOnly,
                    readyOnly,
                    thrashOnly,
                }),
            ],
            activeCard: [
                (s) => [s.stateFilter, s.ciStatusFilter, s.stuckOnly, s.readyOnly, s.thrashOnly],
                (
                    stateFilter: PRStateFilter,
                    ciStatus: CIStatusFilter,
                    stuckOnly: boolean,
                    readyOnly: boolean,
                    thrashOnly: boolean
                ): CardFilter | null => {
                    if (stateFilter !== 'open') {
                        return null
                    }
                    if (stuckOnly) {
                        return 'stuck'
                    }
                    if (readyOnly) {
                        return 'ready'
                    }
                    if (thrashOnly) {
                        return 'thrash'
                    }
                    if (ciStatus === 'failing') {
                        return 'failing'
                    }
                    return ciStatus === 'all' ? 'open' : null
                },
            ],
            filteredPullRequests: [
                (s) => [s.pullRequests, s.filters],
                (pullRequests: PullRequestRow[], filters: PullRequestFilters): PullRequestRow[] =>
                    filterPullRequests(pullRequests, filters),
            ],
            hasActiveFilters: [
                (s) => [s.filters],
                (filters: PullRequestFilters): boolean =>
                    !objectsEqual({ ...filters, search: filters.search.trim() }, DEFAULT_FILTERS),
            ],
            // Counted over the loaded list (the "most recent 1000" cap applies), not a separate backend
            // aggregate like the ci_cards counts — fine while a repo's open backlog fits in that window.
            readyCount: [
                (s) => [s.pullRequests],
                (pullRequests: PullRequestRow[]): number => pullRequests.filter(isReady).length,
            ],
            thrashCount: [
                (s) => [s.pullRequests],
                (pullRequests: PullRequestRow[]): number => pullRequests.filter(isThrashing).length,
            ],
            anyLoading: [
                (s) => [s.cardsLoading, s.pullRequestsLoading, s.workflowHealthLoading, s.quarantineLoading],
                (
                    cardsLoading: boolean,
                    pullRequestsLoading: boolean,
                    workflowHealthLoading: boolean,
                    quarantineLoading: boolean
                ): boolean => cardsLoading || pullRequestsLoading || workflowHealthLoading || quarantineLoading,
            ],
            notConnected: [
                (s) => [s.cardsStatus, s.pullRequestsStatus, s.workflowHealthStatus],
                (
                    cardsStatus: LoaderStatus,
                    pullRequestsStatus: LoaderStatus,
                    workflowHealthStatus: LoaderStatus
                ): boolean => [cardsStatus, pullRequestsStatus, workflowHealthStatus].includes('notConnected'),
            ],
            // Each scene's error state reacts only to the loaders it renders (see LoaderStatus).
            pullRequestsLoadError: [
                (s) => [s.cardsStatus, s.pullRequestsStatus],
                (cardsStatus: LoaderStatus, pullRequestsStatus: LoaderStatus): boolean =>
                    cardsStatus === 'error' || pullRequestsStatus === 'error',
            ],
            workflowHealthLoadError: [
                (s) => [s.workflowHealthStatus],
                (workflowHealthStatus: LoaderStatus): boolean => workflowHealthStatus === 'error',
            ],
            tableTruncated: [
                (s) => [s.pullRequests],
                (pullRequests: PullRequestRow[]): boolean => pullRequests.length >= PR_TABLE_LIMIT,
            ],
            trunkQuarantineTestsByTeam: [
                (s) => [s.trunkQuarantine],
                (trunkQuarantine: TrunkQuarantineData | null): Record<string, TrunkQuarantinedTestRow[]> =>
                    groupBy(trunkQuarantine?.tests ?? [], (test) => test.ownerTeam),
            ],
            hasMultipleSources: [
                (s) => [s.githubSources],
                (githubSources: GitHubSourceApi[]): boolean => githubSources.length > 1,
            ],
            // The source reads resolve to: the picked one, else the backend default (oldest connected = first).
            // Matched by (source, repo), not source alone: a multi-repo source's entries share one id,
            // so headers and commit links reading activeSource.repo must reflect the picked repo, not
            // the first entry with that id.
            activeSource: [
                (s) => [s.githubSources, s.sourceId, s.scopeRepo],
                (
                    githubSources: GitHubSourceApi[],
                    sourceId: string | null,
                    scopeRepo: string | null
                ): GitHubSourceApi | null => {
                    if (!sourceId) {
                        // A repo-only scope (?repo with no ?source) resolves across sources — label that
                        // repo. Otherwise prefer the first *synced* repo, matching the repo the backend
                        // resolves by default (it skips still-backfilling repos), else the first entry.
                        return (
                            (scopeRepo && githubSources.find((source) => source.repo === scopeRepo)) ||
                            githubSources.find((source) => source.synced) ||
                            githubSources[0] ||
                            null
                        )
                    }
                    const ofSource = githubSources.filter((source) => source.id === sourceId)
                    // Explicit repo wins; otherwise (a bookmarked `?source=` with no `?repo`) prefer the
                    // first synced repo of this source, matching the repo the backend resolves by default —
                    // else the header names an unsynced repo the loaders never read.
                    return (
                        (scopeRepo && ofSource.find((source) => source.repo === scopeRepo)) ||
                        ofSource.find((source) => source.synced) ||
                        ofSource[0] ||
                        null
                    )
                },
            ],
            // One option per selectable (source, repo). The value encodes both so a multi-repo source's
            // repos are distinct entries; the label is the repo (falling back to prefix).
            sourceOptions: [
                (s) => [s.githubSources],
                (githubSources: GitHubSourceApi[]): { value: string; label: string }[] =>
                    githubSources.map((source) => ({
                        value: scopeToValue(source.id, source.repo),
                        label: source.repo || source.prefix || `source ${source.id.slice(0, 8)}`,
                    })),
            ],
            // The picker's current value: the entry matching the picked (source, repo), else that source's
            // first entry, else null (unpicked → placeholder + backend default).
            selectedScope: [
                (s) => [s.githubSources, s.sourceId, s.scopeRepo],
                (
                    githubSources: GitHubSourceApi[],
                    sourceId: string | null,
                    scopeRepo: string | null
                ): string | null => {
                    if (!sourceId) {
                        // A repo-only scope (?repo, no ?source) highlights that repo across sources; an
                        // unscoped page highlights nothing (placeholder shows the default label).
                        const byRepo = scopeRepo && githubSources.find((source) => source.repo === scopeRepo)
                        return byRepo ? scopeToValue(byRepo.id, byRepo.repo) : null
                    }
                    // Mirror activeSource: with no explicit repo, prefer the synced entry so the picker
                    // highlights the repo the loaders actually read — else it shows an unsynced repo whose
                    // selection would flip the page to not-connected.
                    const ofSource = githubSources.filter((source) => source.id === sourceId)
                    const match =
                        (scopeRepo && ofSource.find((source) => source.repo === scopeRepo)) ||
                        ofSource.find((source) => source.synced) ||
                        ofSource[0]
                    return match ? scopeToValue(match.id, match.repo) : null
                },
            ],
        }),

        listeners(({ actions, values }) => ({
            refresh: () => {
                actions.loadCards()
                actions.loadPullRequests()
                actions.loadWorkflowHealth()
                actions.loadQuarantine()
                actions.loadTrunkQuarantine()
            },
            setSourceId: () => actions.refresh(),
            setScope: () => actions.refresh(),
            [engineeringAnalyticsFiltersLogic.actionTypes.setDateRange]: () => {
                actions.loadWorkflowHealth()
            },
            [engineeringAnalyticsFiltersLogic.actionTypes.setAppliedBranch]: () => {
                actions.loadWorkflowHealth()
            },
            [engineeringAnalyticsFiltersLogic.actionTypes.scopeToPullRequests]: () => {
                actions.loadWorkflowHealth()
            },
            applyCardFilter: ({ card }) => {
                // Clicking the already-active card toggles back to the plain open view. setStateFilter('open')
                // runs first and clears every lens flag, so the explicit sets below leave exactly one active.
                const target: CardFilter = values.activeCard === card ? 'open' : card
                actions.setStateFilter('open')
                actions.setCiStatusFilter(target === 'failing' ? 'failing' : 'all')
                actions.setStuckOnly(target === 'stuck')
                actions.setReadyOnly(target === 'ready')
                actions.setThrashOnly(target === 'thrash')
            },
        })),

        actionToUrl(() => {
            // Write the (source, repo) scope onto the URL. A source change without a repo drops `?repo`
            // (the old repo belonged to the old source); setScope writes both together.
            const writeScope = (
                sourceId: string | null,
                scopeRepo: string | null
            ): [string, Record<string, string>, Record<string, string>, { replace: boolean }] => {
                const searchParams = { ...router.values.searchParams }
                if (sourceId) {
                    searchParams.source = sourceId
                } else {
                    delete searchParams.source
                }
                if (scopeRepo) {
                    searchParams.repo = scopeRepo
                } else {
                    delete searchParams.repo
                }
                return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
            }
            return {
                setSourceId: ({ sourceId }) => writeScope(sourceId, null),
                setScope: ({ sourceId, scopeRepo }) => writeScope(sourceId, scopeRepo),
            }
        }),

        urlToAction(({ actions, values }) => {
            // `?q=` (branch scope) is hydrated by engineeringAnalyticsFiltersLogic, not here.
            const applyScope = (source: string | undefined, repo: string | undefined): void => {
                const nextSource = source ?? null
                const nextRepo = repo ?? null
                if (nextSource !== values.sourceId || nextRepo !== values.scopeRepo) {
                    actions.setScope(nextSource, nextRepo)
                }
            }
            return {
                [urls.engineeringAnalytics()]: (_, s) => applyScope(s.source, s.repo),
                [urls.engineeringAnalyticsPullRequestList()]: (_, s) => applyScope(s.source, s.repo),
                [urls.engineeringAnalyticsWorkflows()]: (_, s) => applyScope(s.source, s.repo),
                [urls.engineeringAnalyticsTestHealth()]: (_, s) => applyScope(s.source, s.repo),
                [urls.engineeringAnalyticsHealth()]: (_, s) => applyScope(s.source, s.repo),
            }
        }),

        afterMount(({ actions }) => {
            actions.loadGithubSources()
            actions.refresh()
        }),
    ])
