import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { Breadcrumb } from '~/types'

import { visualReviewReposCreate, visualReviewReposList, visualReviewReposPartialUpdate } from '../generated/api'
import type { PatchedUpdateRepoRequestInputApi, RepoApi } from '../generated/api.schemas'
import type { visualReviewSettingsSceneLogicType } from './visualReviewSettingsSceneLogicType'

export interface RepoFormValues {
    name: string
    repo_full_name: string
    baseline_file_paths: Record<string, string>
}

const EMPTY_FORM: RepoFormValues = {
    name: '',
    repo_full_name: '',
    baseline_file_paths: {},
}

function formValuesFromRepo(repo: RepoApi): RepoFormValues {
    return {
        name: repo.name || '',
        repo_full_name: repo.repo_full_name || '',
        baseline_file_paths: repo.baseline_file_paths || {},
    }
}

export const visualReviewSettingsSceneLogic = kea<visualReviewSettingsSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewSettingsSceneLogic']),

    connect(() => ({
        values: [integrationsLogic, ['integrations', 'getGitHubRepositories']],
    })),

    actions({
        editRepo: (repoId: string) => ({ repoId }),
        cancelEdit: true,
        setFormField: (field: keyof RepoFormValues, value: RepoFormValues[keyof RepoFormValues]) => ({ field, value }),
        newRepo: true,
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
                newRepo: () => 'new',
                cancelEdit: () => null,
                loadReposSuccess: () => null,
            },
        ],
        formValues: [
            EMPTY_FORM as RepoFormValues,
            {
                newRepo: () => EMPTY_FORM,
                cancelEdit: () => EMPTY_FORM,
                setFormField: (state, { field, value }) => ({ ...state, [field]: value }),
                loadReposSuccess: () => EMPTY_FORM,
            },
        ],
        saving: [
            false,
            {
                saveRepo: () => true,
                loadReposSuccess: () => false,
                loadReposFailure: () => false,
            },
        ],
    }),

    selectors({
        editingRepo: [
            (s) => [s.repos, s.editingRepoId],
            (repos, editingRepoId): RepoApi | null => {
                if (!editingRepoId || editingRepoId === 'new') {
                    return null
                }
                return repos.find((r) => r.id === editingRepoId) || null
            },
        ],
        hasChanges: [
            (s) => [s.formValues, s.editingRepo, s.editingRepoId],
            (formValues, editingRepo, editingRepoId): boolean => {
                if (editingRepoId === 'new') {
                    return formValues.name.trim().length > 0
                }
                if (!editingRepo) {
                    return false
                }
                return (
                    formValues.name !== (editingRepo.name || '') ||
                    formValues.repo_full_name !== (editingRepo.repo_full_name || '') ||
                    JSON.stringify(formValues.baseline_file_paths) !==
                        JSON.stringify(editingRepo.baseline_file_paths || {})
                )
            },
        ],
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
        editRepo: ({ repoId }) => {
            const repo = values.repos.find((r) => r.id === repoId)
            if (repo) {
                const form = formValuesFromRepo(repo)
                actions.setFormField('name', form.name)
                actions.setFormField('repo_full_name', form.repo_full_name)
                actions.setFormField('baseline_file_paths', form.baseline_file_paths)
            }
        },
        saveRepo: async () => {
            try {
                const { editingRepoId, formValues } = values

                if (editingRepoId === 'new') {
                    const created = await visualReviewReposCreate('@current', {
                        name: formValues.name.trim(),
                    })
                    // After creating, patch with remaining fields
                    const updates: PatchedUpdateRepoRequestInputApi = {
                        repo_full_name: formValues.repo_full_name || null,
                        baseline_file_paths: formValues.baseline_file_paths,
                    }
                    await visualReviewReposPartialUpdate('@current', created.id, updates)
                    lemonToast.success('Repo created')
                } else if (editingRepoId) {
                    const updates: PatchedUpdateRepoRequestInputApi = {
                        name: formValues.name,
                        repo_full_name: formValues.repo_full_name || null,
                        baseline_file_paths: formValues.baseline_file_paths,
                    }
                    await visualReviewReposPartialUpdate('@current', editingRepoId, updates)
                    lemonToast.success('Settings saved')
                }

                actions.loadRepos()
            } catch {
                lemonToast.error('Failed to save')
                // Reset saving state manually since loadRepos won't fire
                actions.loadReposFailure('Save failed')
            }
        },
    })),

    afterMount(({ actions, values }) => {
        actions.loadRepos()
        // Load GitHub repos for the dropdown
        const githubIntegrations = values.integrations?.filter((i: { kind: string }) => i.kind === 'github') || []
        for (const integration of githubIntegrations) {
            integrationsLogic.actions.loadGitHubRepositories(integration.id)
        }
    }),
])
