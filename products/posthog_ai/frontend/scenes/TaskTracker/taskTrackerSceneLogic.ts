import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { ClaudeRuntimeAdapterEnumApi, ReasoningEffortEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import type { SuggestionGroup, SuggestionItem } from '../../api/primitives'
import { DEFAULT_HEADLINES, pickHeadline } from '../../api/primitives'
import { tasksLogic } from '../../logics/tasksLogic'
import type { RepositoryConfig } from '../../types/taskTypes'
import { OriginProduct, TaskUpsertProps } from '../../types/taskTypes'
import { DEFAULT_COMPOSER_EFFORT, DEFAULT_COMPOSER_MODEL, resolveEffortForModel } from '../../utils/composerModels'
import type { taskTrackerSceneLogicType } from './taskTrackerSceneLogicType'

export interface TaskCreateForm {
    description: string
    repositoryConfig: RepositoryConfig
    model: string
    reasoningEffort: ReasoningEffortEnumApi
}

// The slice of the repo picker we remember across visits. Branch is deliberately excluded — on restore we
// want the branch picker to re-derive the repo's actual default branch (from the GitHub API), not pin a stale one.
export type PersistedRepositoryConfig = Pick<RepositoryConfig, 'integrationId' | 'repository'>

const LAST_REPOSITORY_CONFIG_STORAGE_KEY = 'posthog_ai.tasks.lastRepositoryConfig'

const EMPTY_TASK_FORM: TaskCreateForm = {
    description: '',
    repositoryConfig: {
        integrationId: undefined,
        repository: undefined,
    },
    model: DEFAULT_COMPOSER_MODEL,
    reasoningEffort: DEFAULT_COMPOSER_EFFORT,
}

export const taskTrackerSceneLogic = kea<taskTrackerSceneLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'scenes', 'TaskTracker', 'taskTrackerSceneLogic']),

    connect(() => ({
        values: [tasksLogic, ['tasks', 'repositories'], integrationsLogic, ['integrations']],
        actions: [
            tasksLogic,
            ['loadTasks', 'loadRepositories', 'deleteTask'],
            integrationsLogic,
            ['loadIntegrationsSuccess'],
        ],
    })),

    actions({
        maybeRestoreRepositoryConfig: true,
        setPersistedRepositoryConfig: (config: PersistedRepositoryConfig) => ({ config }),
        setActiveSuggestionGroup: (group: SuggestionGroup | null) => ({ group }),
        applySuggestion: (item: SuggestionItem) => ({ item }),
        setHeadline: (headline: string) => ({ headline }),
    }),

    reducers({
        // Last repo/integration the user picked, persisted to localStorage so the composer comes back pre-filled.
        persistedRepositoryConfig: [
            {} as PersistedRepositoryConfig,
            { persist: true, storageKey: LAST_REPOSITORY_CONFIG_STORAGE_KEY },
            {
                setPersistedRepositoryConfig: (_, { config }) => config,
            },
        ],
        activeSuggestionGroup: [
            null as SuggestionGroup | null,
            {
                setActiveSuggestionGroup: (_, { group }) => group,
                // Clearing the description (e.g. after submit/reset) collapses any open dropdown.
                setTaskCreateFormValues: (state, { values: formValues }) =>
                    formValues.description !== undefined && !formValues.description ? null : state,
                resetTaskCreateForm: () => null,
            },
        ],
        headline: [
            DEFAULT_HEADLINES[0],
            {
                setHeadline: (_, { headline }) => headline,
            },
        ],
    }),

    forms(({ actions }) => ({
        taskCreateForm: {
            defaults: EMPTY_TASK_FORM,
            // Only `description` is validated here. `repositoryConfig` is optional — PostHog AI can run without a
            // repo, so the send button is never gated on it; when set, the task is scoped to that repo/branch.
            errors: ({ description }) => ({
                description: !description.trim() ? 'Description is required' : undefined,
            }),
            submit: async ({ description, repositoryConfig, model, reasoningEffort }) => {
                try {
                    const taskData: TaskUpsertProps = {
                        title: '',
                        description,
                        origin_product: OriginProduct.USER_CREATED,
                        repository: repositoryConfig.repository ?? null,
                        github_integration: repositoryConfig.integrationId ?? null,
                    }

                    const newTask = await api.tasks.create(taskData)
                    lemonToast.success('Task created successfully')

                    // Auto-run the task after creation; the detail scene shows the latest run by default. The
                    // run checks out the chosen branch (server falls back to the repo's default branch if unset)
                    // and launches with the picked model / reasoning effort (clamped to one the model supports).
                    await api.tasks.run(newTask.id, {
                        branch: repositoryConfig.branch ?? null,
                        runtime_adapter: ClaudeRuntimeAdapterEnumApi.Claude,
                        model,
                        reasoning_effort: resolveEffortForModel(reasoningEffort, model),
                    })
                    router.actions.push(`/tasks/${newTask.id}`)

                    actions.resetTaskCreateForm()
                    actions.loadTasks()
                    actions.loadRepositories()
                } catch {
                    lemonToast.error('Failed to create task')
                }
            },
        },
    })),

    selectors({
        sendDisabledReason: [
            (s) => [s.taskCreateForm],
            (taskCreateForm): string | undefined =>
                !taskCreateForm.description.trim() ? 'Describe the task first' : undefined,
        ],
    }),

    listeners(({ actions, values }) => ({
        // Remember the repo/integration whenever the picker changes it, so the next visit restores it.
        setTaskCreateFormValues: ({ values: formValues }) => {
            if (formValues.repositoryConfig) {
                const { integrationId, repository } = formValues.repositoryConfig
                actions.setPersistedRepositoryConfig({ integrationId, repository })
            }
        },
        // Restore the remembered repo (or fall back to the first connected GitHub integration) when nothing is
        // chosen yet. The IntegrationChoice picker that used to own this selection is no longer rendered.
        maybeRestoreRepositoryConfig: () => {
            if (values.taskCreateForm.repositoryConfig.integrationId) {
                return
            }
            const githubIntegrations = values.integrations?.filter((integration) => integration.kind === 'github') ?? []
            if (githubIntegrations.length === 0) {
                return
            }
            // Restore the last-used repo only if its integration is still connected. Branch is left unset so
            // GitHubBranchCombobox re-selects the repo's actual default branch.
            const { integrationId, repository } = values.persistedRepositoryConfig
            if (integrationId && githubIntegrations.some((integration) => integration.id === integrationId)) {
                actions.setTaskCreateFormValues({ repositoryConfig: { integrationId, repository } })
                return
            }
            actions.setTaskCreateFormValues({
                repositoryConfig: {
                    ...values.taskCreateForm.repositoryConfig,
                    integrationId: githubIntegrations[0].id,
                },
            })
        },
        loadIntegrationsSuccess: () => {
            actions.maybeRestoreRepositoryConfig()
        },
        // Fill the composer with the suggestion; submit straight away unless it needs the user to finish
        // typing (the component focuses the textarea in that case).
        applySuggestion: ({ item }) => {
            actions.setTaskCreateFormValues({ description: item.content })
            if (!item.requiresUserInput) {
                actions.submitTaskCreateForm()
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadTasks()
            actions.loadRepositories()
            // Roll a headline once per mount (pickHeadline forces index 0 under Storybook for stable snapshots).
            actions.setHeadline(pickHeadline())
            // integrationsLogic loads on its own mount (triggered by the connect above), so we don't call
            // loadIntegrations ourselves. loadIntegrationsSuccess covers that first load; this call covers
            // integrations already cached by an earlier mount.
            actions.maybeRestoreRepositoryConfig()
        },
    })),
])
