import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'

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
export type PRStateFilter = 'open' | 'merged' | 'all'
export type CIStatusFilter = CIStatus | 'all'

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

export interface WorkflowHealthRow {
    workflowName: string
    runCount: number
    /** Over completed runs only; null when nothing has settled yet. */
    successRate: number | null
    p50Seconds: number | null
    p95Seconds: number | null
    lastFailureAt: string | null
}

export interface PullRequestFilters {
    state: PRStateFilter
    author: string | null
    repo: string | null
    ciStatus: CIStatusFilter
    search: string
}

export function filterPullRequests(rows: PullRequestRow[], filters: PullRequestFilters): PullRequestRow[] {
    const search = filters.search.trim().toLowerCase()
    return rows.filter((row) => {
        if (filters.state === 'open' && row.state !== 'open') {
            return false
        }
        if (filters.state === 'merged' && row.state !== 'merged') {
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

export const engineeringAnalyticsLogic = kea<engineeringAnalyticsLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'engineeringAnalyticsLogic']),

    actions({
        setStateFilter: (state: PRStateFilter) => ({ state }),
        setAuthor: (author: string | null) => ({ author }),
        setRepo: (repo: string | null) => ({ repo }),
        setCiStatusFilter: (ciStatus: CIStatusFilter) => ({ ciStatus }),
        setSearch: (search: string) => ({ search }),
        refresh: true,
    }),

    loaders(() => ({
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
                    const items = await engineeringAnalyticsWorkflowHealth(projectId())
                    return items.map(
                        (it): WorkflowHealthRow => ({
                            workflowName: it.workflow_name,
                            runCount: it.run_count,
                            successRate: it.success_rate,
                            p50Seconds: it.p50_seconds,
                            p95Seconds: it.p95_seconds,
                            lastFailureAt: it.last_failure_at,
                        })
                    )
                },
            },
        ],
    })),

    reducers({
        stateFilter: ['open' as PRStateFilter, { setStateFilter: (_, { state }) => state }],
        author: [null as string | null, { setAuthor: (_, { author }) => author }],
        repo: [null as string | null, { setRepo: (_, { repo }) => repo }],
        ciStatusFilter: ['all' as CIStatusFilter, { setCiStatusFilter: (_, { ciStatus }) => ciStatus }],
        search: ['', { setSearch: (_, { search }) => search }],
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
            (s) => [s.stateFilter, s.author, s.repo, s.ciStatusFilter, s.search],
            (stateFilter, author, repo, ciStatus, search): PullRequestFilters => ({
                state: stateFilter,
                author,
                repo,
                ciStatus,
                search,
            }),
        ],
        filteredPullRequests: [
            (s) => [s.pullRequests, s.filters],
            (pullRequests, filters): PullRequestRow[] => filterPullRequests(pullRequests, filters),
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

    listeners(({ actions }) => ({
        refresh: () => {
            actions.loadCards()
            actions.loadPullRequests()
            actions.loadWorkflowHealth()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadCards()
        actions.loadPullRequests()
        actions.loadWorkflowHealth()
    }),
])
