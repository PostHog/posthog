import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { visualReviewReposList } from '../generated/api'
import type { RepoApi } from '../generated/api.schemas'
import type { visualReviewIndexSceneLogicType } from './visualReviewIndexSceneLogicType'

// Index scene logic. Loads the team's repos and replaces the URL with the
// first repo's Runs page when there's exactly one — that's the >99% case.
// When multi-repo grows up we'll render a real picker on this scene instead.
export const visualReviewIndexSceneLogic = kea<visualReviewIndexSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewIndexSceneLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    loaders(({ values }) => ({
        repos: [
            [] as RepoApi[],
            {
                loadRepos: async () => {
                    const response = await visualReviewReposList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
    })),
    selectors({
        breadcrumbs: [() => [], (): Breadcrumb[] => [{ key: 'visual_review', name: 'Visual review' }]],
    }),
    afterMount(({ values, actions }) => {
        actions.loadRepos()
        // If we navigated here while on /visual_review and a repo is already
        // loaded (back/forward navigation re-entering the scene), forward
        // straight away.
        if (values.repos.length === 1) {
            router.actions.replace(urls.visualReviewRepoRuns(values.repos[0].id))
        }
    }),
])
