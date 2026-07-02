import { LogicWrapper, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiConfig, ApiError } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils/objects'
import { urls } from 'scenes/urls'

import {
    engineeringAnalyticsCiCards,
    engineeringAnalyticsPullRequests,
    engineeringAnalyticsQuarantine,
    engineeringAnalyticsQuarantineRequest,
    engineeringAnalyticsSources,
    engineeringAnalyticsWorkflowHealth,
} from '../generated/api'
import type {
    GitHubSourceApi,
    PullRequestListItemApi,
    QuarantineRequestApi,
    QuarantineRequestResultApi,
} from '../generated/api.schemas'
import { CIStatus, ciStatusOf } from '../lib/ci'
import { type FleetSummary, computeFleetSummary } from '../lib/runHealth'
import { engineeringAnalyticsFiltersLogic } from './engineeringAnalyticsFiltersLogic'
import type { engineeringAnalyticsLogicType } from './engineeringAnalyticsLogicType'

// Safety bound on the PR table (mirrors the endpoint's server-side limit). Surfaced
// in copy when hit so a truncated list is never mistaken for the whole picture.
export const PR_TABLE_LIMIT = 1000

// The workflow-health endpoint returns the top workflows by run count (`workflow_health.py` `_LIMIT`).
// When hit, the fleet header labels its totals as "top N" so they're never read as the whole fleet.
export const WORKFLOW_HEALTH_LIMIT = 100

// The endpoints are project-scoped; the generated client takes the id as a string.
const projectId = (): string => String(ApiConfig.getCurrentProjectId())

export type PRState = 'open' | 'closed' | 'merged'
/** 'draft' is a lens over open PRs; the other values mirror PRState. */
export type PRStateFilter = PRState | 'draft' | 'all'
export type CIStatusFilter = CIStatus | 'all'
/** The stat cards double as quick views over the open backlog. */
export type CardFilter = 'open' | 'failing' | 'stuck'

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
    /** Workflow names behind `failing`, sorted — named under the CI tag instead of a bare count. */
    failingWorkflows: string[]
    /** CI triggers in the PR's window: distinct head SHAs across its workflow runs. Fork PRs unattributed. */
    pushes: number
    /** Workflow runs attributed to this PR that were a 2nd+ attempt (a re-run). */
    rerunCycles: number
    /** Estimated CI cost (USD) over the PR's jobs (billable runners). Null when no cost / source unsynced. */
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

/** Bucket width of a workflow's history series. 'hour'/'day'/'week' come from the server (time-bucketed
 *  workflow health); 'push' is computed client-side for the PR view, where each bucket is one push. */
export type WorkflowGranularity = 'hour' | 'day' | 'week' | 'push'

export interface WorkflowHealthBucket {
    /** Bucket start (ISO), aligned to the granularity (top of hour / midnight / Monday). */
    bucketStart: string
    runCount: number
    completed: number
    successes: number
    /** Decisive failures only (failure / timed_out); excludes skipped, cancelled, action_required. */
    failures: number
    /** Pre-formatted sparkline label; when set, used verbatim instead of formatting bucketStart by time
     *  (push buckets aren't time-aligned, so they carry their own "Push N (sha)" label). */
    label?: string
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
    /** Runs in the window that were a 2nd+ attempt — retry pressure. Undefined on per-push rows. */
    rerunCycles?: number
    /** Success rate over the previous equal-length window — the Δpp baseline. Undefined on per-push rows. */
    successRatePrev?: number | null
}

export type WorkflowTrendDirection = 'up' | 'down' | 'flat'

export interface WorkflowFailureSeries {
    /** Completed runs per bucket — drives total (stacked) bar height, i.e. volume. */
    completed: number[]
    /** Decisive failures per bucket — the red portion of each stacked bar. */
    failures: number[]
    /** Per-bucket tooltip label. */
    labels: string[]
}

function formatBucket(bucketStart: string, granularity: WorkflowGranularity): string {
    const at = dayjs(bucketStart)
    if (granularity === 'hour') {
        return at.format('MMM D, HH:mm')
    }
    if (granularity === 'week') {
        return `Week of ${at.format('MMM D')}`
    }
    return at.format('MMM D')
}

/**
 * Series for the run-status sparkline. Each bar is stacked: total height is completed runs (volume)
 * and the red portion is decisive failures, so the red *fraction* reads as the failure rate — 1% is a
 * sliver, 50% is half-red — which length encodes accurately (unlike shade). Skipped, cancelled, and
 * action_required runs are not failures.
 */
export function workflowFailureSeries(
    buckets: WorkflowHealthBucket[],
    granularity: WorkflowGranularity
): WorkflowFailureSeries {
    const completed = buckets.map((b) => b.completed)
    const failures = buckets.map((b) => b.failures)
    const labels = buckets.map((b) => {
        // Push buckets carry their own label (not time-aligned); time buckets format from bucketStart.
        const when = b.label ?? formatBucket(b.bucketStart, granularity)
        return b.completed > 0 ? `${when} · ${b.failures} of ${b.completed} failed` : `${when} · no completed runs`
    })
    return { completed, failures, labels }
}

/** Failure direction: are failures rising in the recent half of the window vs the prior half? */
export function workflowFailureTrend(buckets: WorkflowHealthBucket[]): WorkflowTrendDirection {
    if (buckets.length < 2) {
        return 'flat'
    }
    const mid = Math.floor(buckets.length / 2)
    const sumFailures = (slice: WorkflowHealthBucket[]): number => slice.reduce((total, b) => total + b.failures, 0)
    const prior = sumFailures(buckets.slice(0, mid))
    const recent = sumFailures(buckets.slice(mid))
    if (recent > prior) {
        return 'up'
    }
    if (recent < prior) {
        return 'down'
    }
    return 'flat'
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

/** Map an API PR list item to the table row shape — shared by the PR list and the author page so both
 *  feed the same PullRequestTable. ?? fallbacks degrade gracefully when a new frontend briefly hits an
 *  older backend whose response predates the cost/push fields. */
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
}

export const DEFAULT_FILTERS: PullRequestFilters = {
    state: 'open',
    author: null,
    repo: null,
    ciStatus: 'all',
    search: '',
    stuckOnly: false,
}

export function isStuck(row: PullRequestRow, stuckCutoffMs: number): boolean {
    return row.state === 'open' && !row.isDraft && !row.isBot && Date.parse(row.createdAt) < stuckCutoffMs
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
    // Hoisted out of the per-row check: this selector re-runs on every search keystroke
    // over up to 1000 rows, so the row loop should not allocate dayjs instances.
    const stuckCutoffMs = filters.stuckOnly ? now.subtract(STUCK_AFTER_DAYS, 'day').valueOf() : 0
    return rows.filter((row) => {
        if (!matchesStateFilter(row, filters.state)) {
            return false
        }
        if (filters.stuckOnly && !isStuck(row, stuckCutoffMs)) {
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

/** 'past_expiry' groups in_grace + overdue — the states the quarantine check warns or fails on. */
export type QuarantineLifecycleFilter = 'all' | 'active' | 'expiring_soon' | 'past_expiry'
export type QuarantineModeFilter = QuarantineMode | 'all'
/** The stat cards double as quick filters over the entries, like the PR tab. */
export type QuarantineCard = 'active' | 'expiring_soon' | 'past_expiry' | 'skipped'

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

export interface QuarantineCounts {
    active: number
    expiringSoon: number
    inGrace: number
    overdue: number
    /** in_grace + overdue — everything the quarantine check warns or fails on. */
    pastExpiry: number
    skipped: number
    total: number
}

export interface QuarantineFilters {
    search: string
    lifecycle: QuarantineLifecycleFilter
    mode: QuarantineModeFilter
    owner: string | null
}

export const DEFAULT_QUARANTINE_FILTERS: QuarantineFilters = {
    search: '',
    lifecycle: 'all',
    mode: 'all',
    owner: null,
}

function matchesLifecycleFilter(row: QuarantineEntryRow, lifecycle: QuarantineLifecycleFilter): boolean {
    if (lifecycle === 'all') {
        return true
    }
    if (lifecycle === 'past_expiry') {
        return row.lifecycle === 'in_grace' || row.lifecycle === 'overdue'
    }
    return row.lifecycle === lifecycle
}

export function filterQuarantineEntries(rows: QuarantineEntryRow[], filters: QuarantineFilters): QuarantineEntryRow[] {
    const search = filters.search.trim().toLowerCase()
    return rows.filter((row) => {
        if (!matchesLifecycleFilter(row, filters.lifecycle)) {
            return false
        }
        if (filters.mode !== 'all' && row.mode !== filters.mode) {
            return false
        }
        if (filters.owner && row.owner !== filters.owner) {
            return false
        }
        if (search) {
            const haystack = `${row.id} ${row.reason} ${row.owner}`.toLowerCase()
            if (!haystack.includes(search)) {
                return false
            }
        }
        return true
    })
}

export function quarantineCountsOf(rows: QuarantineEntryRow[]): QuarantineCounts {
    const counts = {
        active: 0,
        expiringSoon: 0,
        inGrace: 0,
        overdue: 0,
        skipped: 0,
        total: rows.length,
    }
    for (const row of rows) {
        if (row.lifecycle === 'active') {
            counts.active++
        } else if (row.lifecycle === 'expiring_soon') {
            counts.expiringSoon++
        } else if (row.lifecycle === 'in_grace') {
            counts.inGrace++
        } else {
            counts.overdue++
        }
        if (row.mode === 'skip') {
            counts.skipped++
        }
    }
    // past_expiry is exactly the expired buckets — derive it so the two can't drift.
    return { ...counts, pastExpiry: counts.inGrace + counts.overdue }
}

export type QuarantineRequestAction = 'quarantine' | 'extend' | 'remove'

/** What the tab submits to the write endpoint; the backend opens the issue + PR. */
export interface QuarantineSubmitInput {
    action: QuarantineRequestAction
    selector: string
    reason: string
    owner: string
    /** Existing tracking issue, carried forward on extend/remove. */
    issue: string
    /** ISO 'YYYY-MM-DD', or null to let the server default to +14 days. */
    expires: string | null
    mode: QuarantineMode
}

/** Open-modal state for quarantine/extend; null when closed. Remove uses a confirm dialog. */
export interface QuarantineModalState {
    action: 'quarantine' | 'extend'
    selector: string
    reason: string
    owner: string
    issue: string
    mode: QuarantineMode
}

/**
 * Suggest an owning team from a product-scoped selector — a confirm-then-edit starting
 * point, since CODEOWNERS here is intentionally sparse. Returns '' when the selector is
 * not product-scoped, so the user just types the owner.
 */
export function inferOwnerFromSelector(selector: string): string {
    const trimmed = selector.trim()
    const product = trimmed.startsWith('product:')
        ? trimmed.slice('product:'.length)
        : (trimmed.match(/^products\/([^/]+)\//)?.[1] ?? '').replace(/_/g, '-')
    return product ? `@PostHog/team-${product}` : ''
}

function toRequestBody(input: QuarantineSubmitInput, repo: string | null): QuarantineRequestApi {
    return {
        // Wire field is 'operation' (a bare 'action' enum collides in the OpenAPI spec).
        operation: input.action,
        selector: input.selector,
        // Write to the repo currently being viewed so the PR lands where the user expects —
        // and the backend skips the most-active-repo warehouse lookup. Null in local dev.
        repo,
        reason: input.reason,
        owner: input.owner,
        issue: input.issue,
        expires: input.expires,
        mode: input.mode,
    }
}

export function quarantineRequestErrorMessage(error: unknown): string {
    const detail = error as { detail?: string; data?: { detail?: string }; message?: string }
    return detail?.detail ?? detail?.data?.detail ?? detail?.message ?? 'Could not complete the quarantine request.'
}

/**
 * Per-loader outcome. The endpoints all resolve the same GitHub source, so a 400
 * (GitHubSourceNotConnectedError) means "connect a source" for every scene; any other
 * failure is a genuine error scoped to the loader that hit it. Tracked per loader so a
 * 500 on one endpoint drives only the scenes that read it — not, say, an error banner on
 * the PR list because workflow health failed.
 */
export type LoaderStatus = 'ok' | 'notConnected' | 'error'

export function loaderStatusFromError(errorObject: unknown): LoaderStatus {
    return errorObject instanceof ApiError && errorObject.status === 400 ? 'notConnected' : 'error'
}

export const engineeringAnalyticsLogic: LogicWrapper<engineeringAnalyticsLogicType> =
    kea<engineeringAnalyticsLogicType>([
        path(['products', 'engineering_analytics', 'frontend', 'scenes', 'engineeringAnalyticsLogic']),

        // The Workflows tab reads the shared CI-analytics window and branch scope; the loader and reload
        // listeners use them.
        connect(() => ({
            values: [engineeringAnalyticsFiltersLogic, ['dateFrom', 'dateTo', 'appliedBranch']],
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
            applyCardFilter: (card: CardFilter) => ({ card }),
            setSourceId: (sourceId: string | null) => ({ sourceId }),
            setCostLensEnabled: (enabled: boolean) => ({ enabled }),
            resetFilters: true,
            setQuarantineSearch: (search: string) => ({ search }),
            setQuarantineLifecycleFilter: (lifecycle: QuarantineLifecycleFilter) => ({ lifecycle }),
            setQuarantineModeFilter: (mode: QuarantineModeFilter) => ({ mode }),
            setQuarantineOwner: (owner: string | null) => ({ owner }),
            applyQuarantineCard: (card: QuarantineCard) => ({ card }),
            resetQuarantineFilters: true,
            openQuarantineModal: (state: QuarantineModalState) => ({ state }),
            closeQuarantineModal: true,
            refresh: true,
        }),

        loaders(({ values }) => ({
            cards: [
                null as CardsData | null,
                {
                    loadCards: async (): Promise<CardsData> => {
                        const data = await engineeringAnalyticsCiCards(projectId(), {
                            source_id: values.sourceId ?? undefined,
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
                            branch: values.appliedBranch || undefined,
                            source_id: values.sourceId ?? undefined,
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
                                // Defensive ?? null: a new frontend can briefly hit an older backend
                                // whose response predates this field — degrade to "unknown", not crash.
                                latestRunFailed: it.latest_run_failed ?? null,
                                latestRunConclusion: it.latest_run_conclusion ?? null,
                                // Defensive ?? 'day': older backends predate adaptive bucketing.
                                granularity: (it.granularity ?? 'day') as WorkflowGranularity,
                                // ?? []: a new frontend can briefly hit an older backend whose response
                                // predates the buckets field during a rolling deploy — degrade, don't crash.
                                buckets: (it.buckets ?? []).map((b) => ({
                                    bucketStart: b.bucket_start,
                                    runCount: b.run_count,
                                    completed: b.completed,
                                    successes: b.successes,
                                    // Defensive ?? 0: a new frontend can briefly hit an older backend whose
                                    // response predates this field — degrade to 0, don't compute NaN bars.
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
            quarantineSubmit: [
                null as QuarantineRequestResultApi | null,
                {
                    submitQuarantine: async ({
                        input,
                    }: {
                        input: QuarantineSubmitInput
                    }): Promise<QuarantineRequestResultApi> => {
                        return await engineeringAnalyticsQuarantineRequest(
                            projectId(),
                            toRequestBody(input, values.quarantine?.repoFullName ?? null)
                        )
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
            // Leaving the open backlog (e.g. switching to Merged) exits the stuck lens — stuck implies open.
            stuckOnly: [
                DEFAULT_FILTERS.stuckOnly,
                {
                    setStuckOnly: (_, { stuckOnly }) => stuckOnly,
                    setStateFilter: () => false,
                    resetFilters: () => DEFAULT_FILTERS.stuckOnly,
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
            // Which connected GitHub source to read; null = the backend default (oldest connected).
            // URL-synced via `source` so it survives tab switches and deep-links into a PR's detail.
            sourceId: [null as string | null, { setSourceId: (_, { sourceId }) => sourceId }],
            // Per-loader status. Each endpoint resolves the same GitHub source, so any one 400 means
            // "not connected" for every scene; a non-400 failure is a per-loader error. Tracked
            // separately (rather than off cards alone) so notConnected and the scene error states can
            // each react to the loaders that actually feed them — see the selectors below.
            cardsStatus: [
                'ok' as LoaderStatus,
                {
                    loadCards: () => 'ok',
                    loadCardsSuccess: () => 'ok',
                    loadCardsFailure: (_, { errorObject }) => loaderStatusFromError(errorObject),
                },
            ],
            quarantineSearch: [
                DEFAULT_QUARANTINE_FILTERS.search,
                {
                    setQuarantineSearch: (_, { search }) => search,
                    resetQuarantineFilters: () => DEFAULT_QUARANTINE_FILTERS.search,
                },
            ],
            quarantineLifecycleFilter: [
                DEFAULT_QUARANTINE_FILTERS.lifecycle,
                {
                    setQuarantineLifecycleFilter: (_, { lifecycle }) => lifecycle,
                    resetQuarantineFilters: () => DEFAULT_QUARANTINE_FILTERS.lifecycle,
                },
            ],
            quarantineModeFilter: [
                DEFAULT_QUARANTINE_FILTERS.mode,
                {
                    setQuarantineModeFilter: (_, { mode }) => mode,
                    resetQuarantineFilters: () => DEFAULT_QUARANTINE_FILTERS.mode,
                },
            ],
            quarantineOwner: [
                DEFAULT_QUARANTINE_FILTERS.owner,
                {
                    setQuarantineOwner: (_, { owner }) => owner,
                    resetQuarantineFilters: () => DEFAULT_QUARANTINE_FILTERS.owner,
                },
            ],
            // The quarantine endpoint only 400s when there is no GitHub source AND no local
            // checkout (production without a source); a failed load is that canary.
            quarantineLoadFailed: [
                false,
                {
                    loadQuarantine: () => false,
                    loadQuarantineSuccess: () => false,
                    loadQuarantineFailure: () => true,
                },
            ],
            // Drives the quarantine/extend modal; remove uses a confirm dialog instead.
            quarantineModal: [
                null as QuarantineModalState | null,
                {
                    openQuarantineModal: (_, { state }) => state,
                    closeQuarantineModal: () => null,
                    // A successful write closes the modal; a failure keeps it open so the user can retry.
                    submitQuarantineSuccess: () => null,
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
            // Cost & performance lens: surfaces per-PR pushes / re-runs / estimated cost. Transient
            // (no persisted/stateful UI in this phase, per SPEC).
            costLensEnabled: [true, { setCostLensEnabled: (_, { enabled }) => enabled }],
        }),

        selectors({
            // Fleet verdict + rollups across every workflow row, for the all-workflows health strip.
            fleetSummary: [
                (s) => [s.workflowHealth],
                (workflowHealth): FleetSummary => computeFleetSummary(workflowHealth),
            ],
            // The endpoint caps at the top workflows by run count; when hit, the header's totals cover only
            // those, so it labels them as "top N" rather than fleet-wide.
            fleetTruncated: [
                (s) => [s.workflowHealth],
                (workflowHealth): boolean => workflowHealth.length >= WORKFLOW_HEALTH_LIMIT,
            ],
            workflowFilters: [
                (s) => [s.workflowSearch, s.workflowStatusFilter],
                (search, status): WorkflowFilters => ({ search, status }),
            ],
            filteredWorkflowHealth: [
                (s) => [s.workflowHealth, s.workflowFilters],
                (workflowHealth, workflowFilters): WorkflowHealthRow[] =>
                    filterWorkflowHealth(workflowHealth, workflowFilters),
            ],
            hasActiveWorkflowFilters: [
                (s) => [s.workflowFilters],
                (workflowFilters): boolean =>
                    !objectsEqual(
                        { ...workflowFilters, search: workflowFilters.search.trim() },
                        DEFAULT_WORKFLOW_FILTERS
                    ),
            ],
            // Cost data rides on the job-level source — until it's synced, every row's cost fields are
            // null and the cost column/tile would be a wall of dashes, so the scenes hide them instead.
            workflowCostAvailable: [
                (s) => [s.workflowHealth],
                (workflowHealth): boolean =>
                    workflowHealth.some((row) => row.billableMinutes != null || row.estimatedCostUsd != null),
            ],
            filters: [
                (s) => [s.stateFilter, s.author, s.repo, s.ciStatusFilter, s.search, s.stuckOnly],
                (stateFilter, author, repo, ciStatus, search, stuckOnly): PullRequestFilters => ({
                    state: stateFilter,
                    author,
                    repo,
                    ciStatus,
                    search,
                    stuckOnly,
                }),
            ],
            activeCard: [
                (s) => [s.stateFilter, s.ciStatusFilter, s.stuckOnly],
                (stateFilter, ciStatus, stuckOnly): CardFilter | null => {
                    if (stateFilter !== 'open') {
                        return null
                    }
                    if (stuckOnly) {
                        return 'stuck'
                    }
                    if (ciStatus === 'failing') {
                        return 'failing'
                    }
                    return ciStatus === 'all' ? 'open' : null
                },
            ],
            filteredPullRequests: [
                (s) => [s.pullRequests, s.filters],
                (pullRequests, filters): PullRequestRow[] => filterPullRequests(pullRequests, filters),
            ],
            hasActiveFilters: [
                (s) => [s.filters],
                (filters): boolean => !objectsEqual({ ...filters, search: filters.search.trim() }, DEFAULT_FILTERS),
            ],
            authorOptions: [
                (s) => [s.pullRequests],
                (pullRequests): string[] =>
                    Array.from(new Set(pullRequests.map((pr) => pr.authorHandle).filter(Boolean))).sort(),
            ],
            repoOptions: [
                (s) => [s.pullRequests],
                (pullRequests): string[] =>
                    Array.from(new Set(pullRequests.map((pr) => `${pr.repoOwner}/${pr.repoName}`))).sort(),
            ],
            anyLoading: [
                (s) => [s.cardsLoading, s.pullRequestsLoading, s.workflowHealthLoading, s.quarantineLoading],
                (cardsLoading, pullRequestsLoading, workflowHealthLoading, quarantineLoading): boolean =>
                    cardsLoading || pullRequestsLoading || workflowHealthLoading || quarantineLoading,
            ],
            // No GitHub source connected: a 400 from any endpoint (they share source resolution).
            // Drives the "connect a source" state on every scene, regardless of which loaders it renders.
            notConnected: [
                (s) => [s.cardsStatus, s.pullRequestsStatus, s.workflowHealthStatus],
                (cardsStatus, pullRequestsStatus, workflowHealthStatus): boolean =>
                    [cardsStatus, pullRequestsStatus, workflowHealthStatus].includes('notConnected'),
            ],
            // Genuine (non-400) failure of a loader the PR scene renders (cards + the PR list). A 500
            // here shows the retryable error; a failure of only workflow health does not, so the PR
            // list isn't hidden behind an error it doesn't depend on.
            pullRequestsLoadError: [
                (s) => [s.cardsStatus, s.pullRequestsStatus],
                (cardsStatus, pullRequestsStatus): boolean => cardsStatus === 'error' || pullRequestsStatus === 'error',
            ],
            // Genuine (non-400) failure of the only loader the Workflows scene renders. Decoupled from
            // cards so workflow health failing surfaces an error there (not a misleading empty table),
            // and a cards-only failure doesn't error a scene whose own data loaded fine.
            workflowHealthLoadError: [
                (s) => [s.workflowHealthStatus],
                (workflowHealthStatus): boolean => workflowHealthStatus === 'error',
            ],
            tableTruncated: [(s) => [s.pullRequests], (pullRequests): boolean => pullRequests.length >= PR_TABLE_LIMIT],
            quarantineFilters: [
                (s) => [s.quarantineSearch, s.quarantineLifecycleFilter, s.quarantineModeFilter, s.quarantineOwner],
                (search, lifecycle, mode, owner): QuarantineFilters => ({ search, lifecycle, mode, owner }),
            ],
            filteredQuarantineEntries: [
                (s) => [s.quarantine, s.quarantineFilters],
                (quarantine, filters): QuarantineEntryRow[] =>
                    quarantine ? filterQuarantineEntries(quarantine.entries, filters) : [],
            ],
            quarantineCounts: [
                (s) => [s.quarantine],
                (quarantine): QuarantineCounts => quarantineCountsOf(quarantine?.entries ?? []),
            ],
            quarantineOwnerOptions: [
                (s) => [s.quarantine],
                (quarantine): string[] =>
                    Array.from(new Set((quarantine?.entries ?? []).map((entry) => entry.owner).filter(Boolean))).sort(),
            ],
            activeQuarantineCard: [
                (s) => [s.quarantineLifecycleFilter, s.quarantineModeFilter],
                (lifecycle, mode): QuarantineCard | null => {
                    if (mode === 'skip' && lifecycle === 'all') {
                        return 'skipped'
                    }
                    if (mode !== 'all') {
                        return null
                    }
                    if (lifecycle === 'active' || lifecycle === 'expiring_soon' || lifecycle === 'past_expiry') {
                        return lifecycle
                    }
                    return null
                },
            ],
            hasActiveQuarantineFilters: [
                (s) => [s.quarantineFilters],
                (filters): boolean =>
                    !objectsEqual({ ...filters, search: filters.search.trim() }, DEFAULT_QUARANTINE_FILTERS),
            ],
            // Only worth a picker when the team has more than one GitHub source connected.
            hasMultipleSources: [(s) => [s.githubSources], (githubSources): boolean => githubSources.length > 1],
            sourceOptions: [
                (s) => [s.githubSources],
                (githubSources): { value: string; label: string }[] =>
                    githubSources.map((source) => ({
                        value: source.id,
                        label: source.repo || source.prefix || `source ${source.id.slice(0, 8)}`,
                    })),
            ],
        }),

        listeners(({ actions, values }) => ({
            refresh: () => {
                actions.loadCards()
                actions.loadPullRequests()
                actions.loadWorkflowHealth()
                actions.loadQuarantine()
            },
            // Cards, the PR list, workflow health, and the quarantine repo are all per-source — reload them all.
            setSourceId: () => actions.refresh(),
            // The shared window and branch scope workflow health; reload it when either changes.
            [engineeringAnalyticsFiltersLogic.actionTypes.setDateRange]: () => {
                actions.loadWorkflowHealth()
            },
            [engineeringAnalyticsFiltersLogic.actionTypes.setAppliedBranch]: () => {
                actions.loadWorkflowHealth()
            },
            applyCardFilter: ({ card }) => {
                // Clicking the already-active card toggles back to the plain open view.
                const target: CardFilter = values.activeCard === card ? 'open' : card
                actions.setStateFilter('open')
                actions.setCiStatusFilter(target === 'failing' ? 'failing' : 'all')
                actions.setStuckOnly(target === 'stuck')
            },
            applyQuarantineCard: ({ card }) => {
                // Toggling a card off clears only the lifecycle/mode lens, leaving search and owner intact.
                const target = values.activeQuarantineCard === card ? null : card
                if (target === 'skipped') {
                    actions.setQuarantineLifecycleFilter('all')
                    actions.setQuarantineModeFilter('skip')
                } else if (target === null) {
                    actions.setQuarantineLifecycleFilter('all')
                    actions.setQuarantineModeFilter('all')
                } else {
                    actions.setQuarantineModeFilter('all')
                    actions.setQuarantineLifecycleFilter(target)
                }
            },
            submitQuarantineSuccess: ({ quarantineSubmit }) => {
                if (!quarantineSubmit) {
                    return
                }
                lemonToast.success(
                    quarantineSubmit.issue_url
                        ? 'Opened a quarantine PR and a tracking issue. It takes effect once the PR merges.'
                        : 'Opened a PR. It takes effect once it merges.',
                    { button: { label: 'View PR', action: () => window.open(quarantineSubmit.pr_url, '_blank') } }
                )
                // Reflect the pending change once it lands; the file is still the source of truth.
                actions.loadQuarantine()
            },
            submitQuarantineFailure: ({ error }) => {
                lemonToast.error(quarantineRequestErrorMessage(error))
            },
        })),

        actionToUrl(() => ({
            setSourceId: ({ sourceId }) => {
                const searchParams = { ...router.values.searchParams }
                if (sourceId) {
                    searchParams.source = sourceId
                } else {
                    delete searchParams.source
                }
                return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
            },
        })),

        urlToAction(({ actions, values }) => {
            // The chosen source rides in `?source=` so it survives tab switches and deep-links into a PR's detail.
            // (The shared branch scope in `?q=` is hydrated by engineeringAnalyticsFiltersLogic, not here.)
            const applySource = (source: string | undefined): void => {
                const next = source ?? null
                if (next !== values.sourceId) {
                    actions.setSourceId(next)
                }
            }
            return {
                [urls.engineeringAnalytics()]: (_, searchParams) => applySource(searchParams.source),
                [urls.engineeringAnalyticsPullRequestList()]: (_, searchParams) => applySource(searchParams.source),
                [urls.engineeringAnalyticsWorkflows()]: (_, searchParams) => applySource(searchParams.source),
                [urls.engineeringAnalyticsTestHealth()]: (_, searchParams) => applySource(searchParams.source),
            }
        }),

        afterMount(({ actions }) => {
            actions.loadGithubSources()
            actions.refresh()
        }),
    ])
