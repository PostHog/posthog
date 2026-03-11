import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { Breadcrumb } from '~/types'

import { visualReviewReposList, visualReviewRunsCountsRetrieve, visualReviewRunsList } from '../generated/api'
import type { RepoApi, ReviewStateCountsApi, RunApi } from '../generated/api.schemas'
import type { visualReviewRunsSceneLogicType } from './visualReviewRunsSceneLogicType'

export type ReviewState = 'needs_review' | 'clean' | 'processing' | 'stale'

export const visualReviewRunsSceneLogic = kea<visualReviewRunsSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewRunsSceneLogic']),

    actions({
        setActiveTab: (tab: ReviewState) => ({ tab }),
    }),

    reducers({
        activeTab: [
            'needs_review' as ReviewState,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),

    loaders(({ values }) => ({
        runs: [
            [] as RunApi[],
            {
                loadRuns: async () => {
                    const response = await visualReviewRunsList('@current', {
                        review_state: values.activeTab,
                    })
                    return response.results
                },
            },
        ],
        counts: [
            { needs_review: 0, clean: 0, processing: 0, stale: 0 } as ReviewStateCountsApi,
            {
                loadCounts: async () => {
                    return await visualReviewRunsCountsRetrieve('@current')
                },
            },
        ],
        repo: [
            null as RepoApi | null,
            {
                loadRepo: async () => {
                    const response = await visualReviewReposList('@current')
                    return response.results[0] || null
                },
            },
        ],
    })),

    selectors({
        repoFullName: [(s) => [s.repo], (repo): string | undefined => repo?.repo_full_name || undefined],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'visual_review',
                    name: 'Visual review',
                    path: '/visual_review',
                },
            ],
        ],
    }),

    listeners(({ actions }) => ({
        setActiveTab: () => {
            actions.loadRuns()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRuns()
        actions.loadCounts()
        actions.loadRepo()
    }),
])
