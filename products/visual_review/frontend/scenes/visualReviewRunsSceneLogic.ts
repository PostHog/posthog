import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { Breadcrumb } from '~/types'

import { visualReviewReposList, visualReviewRunsList } from '../generated/api'
import type { RepoApi, RunApi } from '../generated/api.schemas'
import type { visualReviewRunsSceneLogicType } from './visualReviewRunsSceneLogicType'

export type RunFilterTab = 'needs_review' | 'clean' | 'processing'

export const visualReviewRunsSceneLogic = kea<visualReviewRunsSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewRunsSceneLogic']),

    actions({
        setActiveTab: (tab: RunFilterTab) => ({ tab }),
    }),

    reducers({
        activeTab: [
            'needs_review' as RunFilterTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),

    loaders({
        runs: [
            [] as RunApi[],
            {
                loadRuns: async () => {
                    const response = await visualReviewRunsList('@current')
                    return response.results
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
    }),

    selectors({
        needsReviewRuns: [
            (s) => [s.runs],
            (runs): RunApi[] =>
                runs.filter(
                    (r) =>
                        r.status === 'completed' &&
                        (r.summary.changed > 0 || r.summary.new > 0 || r.summary.removed > 0) &&
                        !r.approved
                ),
        ],
        cleanRuns: [
            (s) => [s.runs],
            (runs): RunApi[] =>
                runs.filter(
                    (r) =>
                        (r.status === 'completed' &&
                            r.summary.changed === 0 &&
                            r.summary.new === 0 &&
                            r.summary.removed === 0) ||
                        r.approved
                ),
        ],
        processingRuns: [
            (s) => [s.runs],
            (runs): RunApi[] => runs.filter((r) => r.status === 'pending' || r.status === 'processing'),
        ],
        filteredRuns: [
            (s) => [s.activeTab, s.needsReviewRuns, s.cleanRuns, s.processingRuns],
            (activeTab, needsReviewRuns, cleanRuns, processingRuns): RunApi[] => {
                switch (activeTab) {
                    case 'needs_review':
                        return needsReviewRuns
                    case 'clean':
                        return cleanRuns
                    case 'processing':
                        return processingRuns
                    default:
                        return []
                }
            },
        ],
        tabCounts: [
            (s) => [s.needsReviewRuns, s.cleanRuns, s.processingRuns],
            (
                needsReviewRuns,
                cleanRuns,
                processingRuns
            ): { needs_review: number; clean: number; processing: number } => ({
                needs_review: needsReviewRuns.length,
                clean: cleanRuns.length,
                processing: processingRuns.length,
            }),
        ],
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

    afterMount(({ actions }) => {
        actions.loadRuns()
        actions.loadRepo()
    }),
])
