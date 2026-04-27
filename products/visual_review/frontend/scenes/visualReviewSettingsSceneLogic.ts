import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { z } from 'zod'

import { parseWithStandardSchema, standardSchemaToKeaErrors } from 'lib/forms/standard-schema'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import { visualReviewReposCreate, visualReviewReposList, visualReviewReposPartialUpdate } from '../generated/api'
import type { PatchedUpdateRepoRequestInputApi, RepoApi } from '../generated/api.schemas'
import { VisualReviewReposPartialUpdateBody } from '../generated/api.zod'
import type { visualReviewSettingsSceneLogicType } from './visualReviewSettingsSceneLogicType'

export interface RepoFormValues {
    baseline_file_paths: Record<string, string>
    enable_pr_comments: boolean
}

const repoFormSchema = VisualReviewReposPartialUpdateBody.extend({
    baseline_file_paths: z
        .record(z.string().min(1, 'Run type is required'), z.string().min(1, 'Path is required'))
        .default({}),
    enable_pr_comments: z.boolean().default(false),
})

const EMPTY_FORM: RepoFormValues = {
    baseline_file_paths: {},
    enable_pr_comments: false,
}

function formValuesFromRepo(repo: RepoApi): RepoFormValues {
    return {
        baseline_file_paths: repo.baseline_file_paths || {},
        enable_pr_comments: repo.enable_pr_comments,
    }
}

export const visualReviewSettingsSceneLogic = kea<visualReviewSettingsSceneLogicType>([
    path(['products', 'visual_review', 'frontend', 'scenes', 'visualReviewSettingsSceneLogic']),

    connect(() => ({
        values: [integrationsLogic, ['integrations', 'getGitHubRepositoriesFull'], teamLogic, ['currentProjectId']],
        actions: [integrationsLogic, ['loadIntegrationsSuccess']],
    })),

    actions({
        editRepo: (repoId: string) => ({ repoId }),
        cancelEdit: true,
        addRepo: (githubRepo: GitHubRepoApi) => ({ githubRepo }),
        saveRepo: true,
    }),

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

    reducers({
        editingRepoId: [
            null as string | null,
            {
                editRepo: (_, { repoId }) => repoId,
                cancelEdit: () => null,
                loadReposSuccess: () => null,
            },
        ],
    }),

    forms(({ actions, values }) => ({
        repoForm: {
            defaults: EMPTY_FORM,
            errors: (values) => standardSchemaToKeaErrors(repoFormSchema, values),
            submit: async (formValues) => {
                try {
                    const parsed = parseWithStandardSchema(repoFormSchema, formValues)
                    if (!parsed.success) {
                        return
                    }
                    if (values.editingRepoId) {
                        const updates: PatchedUpdateRepoRequestInputApi = {
                            baseline_file_paths: parsed.data.baseline_file_paths,
                            enable_pr_comments: parsed.data.enable_pr_comments,
                        }
                        await visualReviewReposPartialUpdate(
                            String(values.currentProjectId),
                            values.editingRepoId,
                            updates
                        )
                        lemonToast.success('Settings saved')
                    }

                    actions.loadRepos()
                } catch {
                    lemonToast.error('Failed to save')
                    actions.loadReposFailure('Save failed')
                }
            },
        },
    })),

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
            (s) => [s.repoForm, s.editingRepo],
            (repoForm, editingRepo): boolean => {
                if (!editingRepo) {
                    return false
                }
                return (
                    JSON.stringify(repoForm.baseline_file_paths) !==
                        JSON.stringify(editingRepo.baseline_file_paths || {}) ||
                    repoForm.enable_pr_comments !== editingRepo.enable_pr_comments
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
                    const accountType = github?.config?.account?.type
                    const accountName = github?.config?.account?.name
                    if (accountType === 'Organization' && accountName) {
                        return `https://github.com/organizations/${accountName}/settings/installations/${installationId}`
                    }
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
                actions.setRepoFormValues(formValuesFromRepo(repo))
            }
        },
        cancelEdit: () => {
            actions.resetRepoForm()
        },
        saveRepo: () => {
            actions.submitRepoForm()
        },
        addRepo: async ({ githubRepo }) => {
            try {
                await visualReviewReposCreate(String(values.currentProjectId), {
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
    })),

    afterMount(({ actions }) => {
        actions.loadRepos()
    }),
])
