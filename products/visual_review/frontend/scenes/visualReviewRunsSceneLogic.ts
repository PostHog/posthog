import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import { visualReviewReposRunsCountsRetrieve, visualReviewReposRunsList } from '../generated/api'
import type { PaginatedRunListApi, RepoApi, ReviewStateCountsApi } from '../generated/api.schemas'
import { visualReviewRepoLogic } from './visualReviewRepoLogic'
import type { visualReviewRunsSceneLogicType } from './visualReviewRunsSceneLogicType'

export type ReviewState = 'needs_review' | 'clean' | 'processing' | 'stale'

const RUNS_PAGE_SIZE = 20

export interface VisualReviewRunsSceneLogicProps {
    repoId: string
}

export const visualReviewRunsSceneLogic = kea<visualReviewRunsSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewRunsSceneLogic']),
    props({} as VisualReviewRunsSceneLogicProps),
    key((props) => props.repoId),

    connect((props: VisualReviewRunsSceneLogicProps) => ({
        values: [
            teamLogic,
            ['currentProjectId'],
            visualReviewRepoLogic({ repoId: props.repoId }),
            ['repo', 'repoFullName'],
        ],
    })),

    actions({
        setActiveTab: (tab: ReviewState) => ({ tab }),
        setPage: (page: number) => ({ page }),
    }),

    reducers({
        activeTab: [
            'needs_review' as ReviewState,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setActiveTab: () => 1,
            },
        ],
    }),

    loaders(({ props, values }) => ({
        runsResponse: [
            { count: 0, results: [] } as PaginatedRunListApi,
            {
                loadRuns: async () => {
                    const offset = (values.page - 1) * RUNS_PAGE_SIZE
                    return await visualReviewReposRunsList(String(values.currentProjectId), props.repoId, {
                        review_state: values.activeTab,
                        limit: RUNS_PAGE_SIZE,
                        offset,
                    })
                },
            },
        ],
        counts: [
            { needs_review: 0, clean: 0, processing: 0, stale: 0 } as ReviewStateCountsApi,
            {
                loadCounts: async () => {
                    return await visualReviewReposRunsCountsRetrieve(String(values.currentProjectId), props.repoId)
                },
            },
        ],
    })),

    selectors({
        repoId: [() => [(_, p) => p.repoId], (repoId: string): string => repoId],
        runs: [
            (s) => [s.runsResponse],
            (runsResponse: PaginatedRunListApi): PaginatedRunListApi['results'] => runsResponse.results,
        ],
        runsLoading: [(s) => [s.runsResponseLoading], (loading: boolean): boolean => loading],
        totalCount: [(s) => [s.runsResponse], (runsResponse: PaginatedRunListApi): number => runsResponse.count ?? 0],
        // Only one scene-level crumb — the project crumb is prepended
        // automatically. With two scene crumbs the SceneTitleSection back
        // button kicks in (it shows when total breadcrumbs > 2), and
        // clicking back lands on /visual_review which immediately redirects
        // straight here, so the back arrow does nothing useful.
        breadcrumbs: [
            (s) => [s.repo],
            (repo: RepoApi | null): Breadcrumb[] => [
                {
                    key: ['visual_review_repo', repo?.id ?? 'unknown'],
                    name: repo?.repo_full_name ?? 'Visual review',
                },
            ],
        ],
    }),

    listeners(({ actions }) => ({
        setActiveTab: () => {
            actions.loadRuns()
        },
        setPage: () => {
            actions.loadRuns()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRuns()
        actions.loadCounts()
    }),
])
