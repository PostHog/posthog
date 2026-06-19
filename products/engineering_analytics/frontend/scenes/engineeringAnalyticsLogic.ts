import { LogicWrapper, actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils/objects'

import {
    engineeringAnalyticsCiCards,
    engineeringAnalyticsPullRequests,
    engineeringAnalyticsWorkflowHealth,
} from '../generated/api'
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
                (s) => [s.cardsLoading, s.pullRequestsLoading, s.workflowHealthLoading],
                (cardsLoading, pullRequestsLoading, workflowHealthLoading): boolean =>
                    cardsLoading || pullRequestsLoading || workflowHealthLoading,
            ],
            tableTruncated: [(s) => [s.pullRequests], (pullRequests): boolean => pullRequests.length >= PR_TABLE_LIMIT],
        }),

        listeners(({ actions, values }) => ({
            refresh: () => {
                actions.loadCards()
                actions.loadPullRequests()
                actions.loadWorkflowHealth()
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
        })),

        afterMount(({ actions }) => {
            actions.loadCards()
            actions.loadPullRequests()
            actions.loadWorkflowHealth()
        }),
    ])
