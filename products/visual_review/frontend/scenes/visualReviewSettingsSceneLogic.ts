import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { GitHubRepoApi } from '~/generated/core/api.schemas'
import { Breadcrumb } from '~/types'

import { visualReviewReposCreate, visualReviewReposList, visualReviewReposPartialUpdate } from '../generated/api'
import type { PatchedUpdateRepoRequestInputApi, RepoApi } from '../generated/api.schemas'
import type { visualReviewSettingsSceneLogicType } from './visualReviewSettingsSceneLogicType'

export interface RepoFormValues {
    baseline_file_paths: Record<string, string>
}

const EMPTY_FORM: RepoFormValues = {
    baseline_file_paths: {},
}

function formValuesFromRepo(repo: RepoApi): RepoFormValues {
    return {
        baseline_file_paths: repo.baseline_file_paths || {},
    }
}

export const visualReviewSettingsSceneLogic = kea<visualReviewSettingsSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewSettingsSceneLogic']),

    connect(() => ({
        values: [integrationsLogic, ['integrations', 'getGitHubRepositoriesFull']],
        actions: [integrationsLogic, ['loadIntegrationsSuccess']],
    })),

    actions({
        editRepo: (repoId: string) => ({ repoId }),
        cancelEdit: true,
        setFormField: (field: keyof RepoFormValues, value: RepoFormValues[keyof RepoFormValues]) => ({ field, value }),
        addRepo: (githubRepo: GitHubRepoApi) => ({ githubRepo }),
        saveRepo: true,
    }),

    loaders({
        repos: [
            [] as RepoApi[],
            {
                loadRepos: async () => {
                    const response = await visualReviewReposList('@current')
                    return response.results
                },
            },
        ],
    }),

    reducers({
        editingRepoId: [
            null as string | null,
            {
                editRepo: (_, { repoId }) => repoId,
                cancelEdit: () => null,
                loadReposSuccess: () => null,
            },
        ],
        formValues: [
            EMPTY_FORM as RepoFormValues,
            {
                cancelEdit: () => EMPTY_FORM,
                setFormField: (state, { field, value }) => ({ ...state, [field]: value }),
                loadReposSuccess: () => EMPTY_FORM,
            },
        ],
        saving: [
            false,
            {
                saveRepo: () => true,
                addRepo: () => true,
                loadReposSuccess: () => false,
                loadReposFailure: () => false,
            },
        ],
    }),

    selectors({
        editingRepo: [
            (s) => [s.repos, s.editingRepoId],
            (repos, editingRepoId): RepoApi | null => {
                if (!editingRepoId) {
                    return null
                }
                return repos.find((r) => r.id === editingRepoId) || null
            },
        ],
        hasChanges: [
            (s) => [s.formValues, s.editingRepo],
            (formValues, editingRepo): boolean => {
                if (!editingRepo) {
                    return false
                }
                return (
                    JSON.stringify(formValues.baseline_file_paths) !==
                    JSON.stringify(editingRepo.baseline_file_paths || {})
                )
            },
        ],
        availableRepos: [
            (s) => [s.integrations, s.getGitHubRepositoriesFull],
            (
                integrations: any[] | null,
                getGitHubRepositoriesFull: (id: number) => GitHubRepoApi[]
            ): GitHubRepoApi[] => {
                const repos: GitHubRepoApi[] = []
                const githubIntegrations = integrations?.filter((i: { kind: string }) => i.kind === 'github') || []

                for (const integration of githubIntegrations) {
                    const integrationRepos = getGitHubRepositoriesFull(integration.id) || []
                    repos.push(...integrationRepos)
                }
                return repos
            },
        ],
        existingRepoNames: [(s) => [s.repos], (repos): Set<string> => new Set(repos.map((r) => r.repo_full_name))],
        githubManageAccessUrl: [
            (s) => [s.integrations],
            (integrations: any[] | null): string | null => {
                const github = integrations?.find((i: { kind: string }) => i.kind === 'github')
                const installationId = github?.config?.installation_id
                if (installationId) {
                    return `https://github.com/settings/installations/${installationId}`
                }
                return null
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
        loadIntegrationsSuccess: () => {
            const githubIntegrations = values.integrations?.filter((i: { kind: string }) => i.kind === 'github') || []
            for (const integration of githubIntegrations) {
                integrationsLogic.actions.loadGitHubRepositories(integration.id)
            }
        },
        editRepo: ({ repoId }) => {
            const repo = values.repos.find((r) => r.id === repoId)
            if (repo) {
                const form = formValuesFromRepo(repo)
                actions.setFormField('baseline_file_paths', form.baseline_file_paths)
            }
        },
        addRepo: async ({ githubRepo }) => {
            try {
                await visualReviewReposCreate('@current', {
                    repo_external_id: githubRepo.id,
                    repo_full_name: githubRepo.full_name,
                })
                lemonToast.success(`Added ${githubRepo.full_name}`)
                actions.loadRepos()
            } catch {
                lemonToast.error('Failed to add repo')
                actions.loadReposFailure('Add failed')
            }
        },
        saveRepo: async () => {
            try {
                const { editingRepoId, formValues } = values

                if (editingRepoId) {
                    const updates: PatchedUpdateRepoRequestInputApi = {
                        baseline_file_paths: formValues.baseline_file_paths,
                    }
                    await visualReviewReposPartialUpdate('@current', editingRepoId, updates)
                    lemonToast.success('Settings saved')
                }

                actions.loadRepos()
            } catch {
                lemonToast.error('Failed to save')
                actions.loadReposFailure('Save failed')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRepos()
    }),
])
