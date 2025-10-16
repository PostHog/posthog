import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { RepositoryConfig } from './RepositorySelector'
import type { repositorySelectorLogicType } from './repositorySelectorLogicType'

export interface AvailableRepo {
    integration_id: number
    organization: string
    repositories: string[]
}

export const repositorySelectorLogic = kea<repositorySelectorLogicType>([
    path(['products', 'tasks', 'frontend', 'components', 'repositorySelectorLogic']),

    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations', 'loadGitHubRepositories']],
        values: [integrationsLogic, ['integrations', 'getGitHubRepositories']],
    })),

    actions({
        setAvailableRepos: (repos: AvailableRepo[]) => ({ repos }),
        setOnChangeCallback: (callback: (config: RepositoryConfig) => void) => ({ callback }),
        setCurrentConfig: (config: RepositoryConfig) => ({ config }),
        tryAutoSelectFirstIntegration: true,
    }),

    reducers({
        availableRepos: [
            [] as AvailableRepo[],
            {
                setAvailableRepos: (_, { repos }) => repos,
            },
        ],
        onChangeCallback: [
            null as ((config: RepositoryConfig) => void) | null,
            {
                setOnChangeCallback: (_, { callback }) => callback,
            },
        ],
        currentConfig: [
            {} as RepositoryConfig,
            {
                setCurrentConfig: (_, { config }) => config,
            },
        ],
    }),

    selectors({
        githubIntegrations: [
            (s) => [s.integrations],
            (integrations) => integrations?.filter((integration) => integration.kind === 'github') || [],
        ],
    }),

    afterMount(({ actions }) => {
        // Load data when logic mounts
        actions.loadIntegrations()
    }),

    listeners(({ actions, values }) => ({
        [integrationsLogic.actionTypes.loadIntegrationsSuccess]: () => {
            if (values.githubIntegrations.length > 0) {
                values.githubIntegrations.forEach((integration) => {
                    actions.loadGitHubRepositories(integration.id)
                })
            }
        },

        [integrationsLogic.actionTypes.loadGitHubRepositoriesSuccess]: () => {
            if (values.githubIntegrations.length > 0) {
                const repoData: AvailableRepo[] = []

                for (const integration of values.githubIntegrations) {
                    const repos = values.getGitHubRepositories(integration.id)

                    repoData.push({
                        integration_id: integration.id,
                        organization: integration.config?.account?.name || 'GitHub',
                        repositories: repos || [],
                    })
                }

                actions.setAvailableRepos(repoData)
                actions.tryAutoSelectFirstIntegration()
            }
        },

        tryAutoSelectFirstIntegration: () => {
            const config = values.currentConfig
            const onChange = values.onChangeCallback

            if (
                onChange &&
                !config.integrationId &&
                values.githubIntegrations.length > 0 &&
                values.availableRepos.length > 0
            ) {
                const firstIntegration = values.githubIntegrations[0]
                const firstRepoData = values.availableRepos.find((r: any) => r.integration_id === firstIntegration.id)

                onChange({
                    ...config,
                    integrationId: firstIntegration.id,
                    organization: firstRepoData?.organization || firstIntegration.config?.account?.name || 'GitHub',
                    repository: firstRepoData?.repositories[0] || '',
                })
            }
        },
    })),
])
