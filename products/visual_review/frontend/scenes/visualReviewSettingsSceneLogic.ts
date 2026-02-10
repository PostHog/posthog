import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { Breadcrumb } from '~/types'

import { visualReviewReposCreate, visualReviewReposList, visualReviewReposPartialUpdate } from '../generated/api'
import type { PatchedUpdateRepoRequestInputApi, RepoApi } from '../generated/api.schemas'
import type { visualReviewSettingsSceneLogicType } from './visualReviewSettingsSceneLogicType'

export const visualReviewSettingsSceneLogic = kea<visualReviewSettingsSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewSettingsSceneLogic']),

    connect(() => ({
        values: [integrationsLogic, ['integrations', 'getGitHubRepositories']],
    })),

    actions({
        saveRepo: (updates: PatchedUpdateRepoRequestInputApi) => ({ updates }),
    }),

    loaders({
        repo: [
            null as RepoApi | null,
            {
                loadRepo: async () => {
                    const response = await visualReviewReposList('@current')
                    if (response.results.length > 0) {
                        return response.results[0]
                    }
                    // No repo exists - will create on first save
                    return null
                },
            },
        ],
    }),

    reducers({
        saving: [
            false,
            {
                saveRepo: () => true,
                saveRepoSuccess: () => false,
                saveRepoFailure: () => false,
            },
        ],
    }),

    selectors({
        availableRepos: [
            (s) => [s.integrations, s.getGitHubRepositories],
            (integrations: any[] | null, getGitHubRepositories: (id: number) => string[]): string[] => {
                const repos: string[] = []
                const githubIntegrations = integrations?.filter((i: { kind: string }) => i.kind === 'github') || []

                for (const integration of githubIntegrations) {
                    const org = integration.config?.account?.name || ''
                    const repoNames = getGitHubRepositories(integration.id) || []
                    for (const repoName of repoNames) {
                        repos.push(`${org}/${repoName}`)
                    }
                }

                return repos
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'visual_review',
                    name: 'Visual review',
                    path: '/visual_review',
                },
                {
                    key: 'visual_review_settings',
                    name: 'Settings',
                    path: '/visual_review/settings',
                },
            ],
        ],
    }),

    listeners(({ values, actions }) => ({
        saveRepo: async ({ updates }) => {
            try {
                let repo = values.repo
                if (!repo) {
                    // Create repo first
                    repo = await visualReviewReposCreate('@current')
                }
                const updated = await visualReviewReposPartialUpdate('@current', repo.id, updates)
                actions.loadRepoSuccess(updated)
                lemonToast.success('Settings saved')
            } catch {
                lemonToast.error('Failed to save settings')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRepo()
    }),
])
