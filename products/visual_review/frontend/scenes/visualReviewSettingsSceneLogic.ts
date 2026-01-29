import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { Breadcrumb } from '~/types'

import {
    visualReviewProjectsCreate,
    visualReviewProjectsList,
    visualReviewProjectsPartialUpdate,
} from '../generated/api'
import type { PatchedUpdateProjectInputApi, ProjectApi } from '../generated/api.schemas'
import type { visualReviewSettingsSceneLogicType } from './visualReviewSettingsSceneLogicType'

export const visualReviewSettingsSceneLogic = kea<visualReviewSettingsSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewSettingsSceneLogic']),

    connect(() => ({
        values: [integrationsLogic, ['integrations', 'getGitHubRepositories']],
    })),

    actions({
        saveProject: (updates: PatchedUpdateProjectInputApi) => ({ updates }),
    }),

    loaders({
        project: [
            null as ProjectApi | null,
            {
                loadProject: async () => {
                    const response = await visualReviewProjectsList('@current')
                    if (response.results.length > 0) {
                        return response.results[0]
                    }
                    // No project exists - will create on first save
                    return null
                },
            },
        ],
    }),

    reducers({
        saving: [
            false,
            {
                saveProject: () => true,
                saveProjectSuccess: () => false,
                saveProjectFailure: () => false,
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
        saveProject: async ({ updates }) => {
            try {
                let project = values.project
                if (!project) {
                    // Create project first
                    project = await visualReviewProjectsCreate('@current')
                }
                const updated = await visualReviewProjectsPartialUpdate('@current', project.id, updates)
                actions.loadProjectSuccess(updated)
                lemonToast.success('Settings saved')
            } catch {
                lemonToast.error('Failed to save settings')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadProject()
    }),
])
