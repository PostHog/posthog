import { LogicWrapper, actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils'

import {
    engineeringAnalyticsCiCards,
    engineeringAnalyticsPullRequests,
    engineeringAnalyticsQuarantine,
    engineeringAnalyticsQuarantineRequest,
    engineeringAnalyticsWorkflowHealth,
} from '../generated/api'
import type { QuarantineRequestApi, QuarantineRequestResultApi } from '../generated/api.schemas'
import { CIStatus, ciStatusOf } from '../lib/ci'
import type { engineeringAnalyticsLogicType } from './engineeringAnalyticsLogicType'

// Safety bound on the PR table (mirrors the endpoint's server-side limit). Surfaced
// in copy when hit so a truncated list is never mistaken for the whole picture.
export const PR_TABLE_LIMIT = 1000

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

/** Mirrors the workflow_health endpoint's default window. */
export const DEFAULT_WORKFLOW_DATE_FROM = '-30d'

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
}

export interface CardsData {
    openPrs: number
    repos: number
    stuck: number
    failingCi: number
}

export interface WorkflowHealthDay {
    /** UTC calendar day. */
    day: string
    runCount: number
    completed: number
    successes: number
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
    /** Zero-filled across the whole window, oldest first. */
    daily: WorkflowHealthDay[]
}

/**
 * Daily series for the trend sparkline. Bar height is the non-pass rate over runs
 * that completed that day, so healthy rows stay flat and bad days spike.
 */
export function workflowTrendSeries(daily: WorkflowHealthDay[]): { values: number[]; labels: string[] } {
    const values = daily.map((d) => (d.completed > 0 ? (d.completed - d.successes) / d.completed : 0))
    const labels = daily.map((d) => {
        const date = dayjs(d.day).format('MMM D')
        return d.completed > 0
            ? `${date} · ${d.completed - d.successes} of ${d.completed} non-passing`
            : `${date} · no completed runs`
    })
    return { values, labels }
}

export function prKeyOf(row: Pick<PullRequestRow, 'repoOwner' | 'repoName' | 'number'>): string {
    return `${row.repoOwner}/${row.repoName}#${row.number}`
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

export interface EngineeringAnalyticsLogicProps {
    tabId?: string
}

export const engineeringAnalyticsLogic: LogicWrapper<engineeringAnalyticsLogicType> =
    kea<engineeringAnalyticsLogicType>([
        props({} as EngineeringAnalyticsLogicProps),
        // One instance per internal tab so filters and loading state don't bleed across tabs.
        key((props) => props.tabId ?? 'default'),
        path((key) => ['products', 'engineering_analytics', 'frontend', 'scenes', 'engineeringAnalyticsLogic', key]),

        actions({
            setStateFilter: (state: PRStateFilter) => ({ state }),
            setAuthor: (author: string | null) => ({ author }),
            setRepo: (repo: string | null) => ({ repo }),
            setCiStatusFilter: (ciStatus: CIStatusFilter) => ({ ciStatus }),
            setSearch: (search: string) => ({ search }),
            setStuckOnly: (stuckOnly: boolean) => ({ stuckOnly }),
            setWorkflowDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
            applyCardFilter: (card: CardFilter) => ({ card }),
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
                        const data = await engineeringAnalyticsCiCards(projectId())
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
                        const response = await engineeringAnalyticsPullRequests(projectId())
                        return response.items.map(
                            (it): PullRequestRow => ({
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
                            })
                        )
                    },
                },
            ],
            workflowHealth: [
                [] as WorkflowHealthRow[],
                {
                    loadWorkflowHealth: async (): Promise<WorkflowHealthRow[]> => {
                        const items = await engineeringAnalyticsWorkflowHealth(projectId(), {
                            date_from: values.workflowDateFrom ?? undefined,
                            date_to: values.workflowDateTo ?? undefined,
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
                                daily: it.daily.map((d) => ({
                                    day: d.day,
                                    runCount: d.run_count,
                                    completed: d.completed,
                                    successes: d.successes,
                                })),
                            })
                        )
                    },
                },
            ],
            quarantine: [
                null as QuarantineData | null,
                {
                    loadQuarantine: async (): Promise<QuarantineData> => {
                        const data = await engineeringAnalyticsQuarantine(projectId())
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
            workflowDateFrom: [
                DEFAULT_WORKFLOW_DATE_FROM as string | null,
                { setWorkflowDateRange: (_, { dateFrom }) => dateFrom },
            ],
            workflowDateTo: [null as string | null, { setWorkflowDateRange: (_, { dateTo }) => dateTo }],
            // Leaving the open backlog (e.g. switching to Merged) exits the stuck lens — stuck implies open.
            stuckOnly: [
                DEFAULT_FILTERS.stuckOnly,
                {
                    setStuckOnly: (_, { stuckOnly }) => stuckOnly,
                    setStateFilter: () => false,
                    resetFilters: () => DEFAULT_FILTERS.stuckOnly,
                },
            ],
            // The endpoints 400 when the team has no GitHub warehouse source connected.
            // A failed cards load is the canary for "no source connected".
            loadFailed: [
                false,
                {
                    loadCards: () => false,
                    loadCardsSuccess: () => false,
                    loadCardsFailure: () => true,
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
        }),

        selectors({
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
        }),

        listeners(({ actions, values }) => ({
            refresh: () => {
                actions.loadCards()
                actions.loadPullRequests()
                actions.loadWorkflowHealth()
                actions.loadQuarantine()
            },
            setWorkflowDateRange: () => {
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

        afterMount(({ actions }) => {
            actions.loadCards()
            actions.loadPullRequests()
            actions.loadWorkflowHealth()
            actions.loadQuarantine()
        }),
    ])
