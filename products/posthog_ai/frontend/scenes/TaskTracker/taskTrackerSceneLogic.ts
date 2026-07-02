import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { uuid } from 'lib/utils/dom'

import {
    ClaudeRuntimeAdapterEnumApi,
    ReasoningEffortEnumApi,
    TaskExecutionModeEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { runStreamLogic } from '../../api/logics'
import type { SuggestionGroup, SuggestionItem } from '../../api/primitives'
import { DEFAULT_HEADLINES, pickHeadline } from '../../api/primitives'
import { tasksLogic } from '../../logics/tasksLogic'
import type { RepositoryConfig, Task } from '../../types/taskTypes'
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

// The optimistic run opened on send, before the task/run exist. `streamKey` is the client key the pending
// `RunSurface` (and its seeded `runStreamLogic`) bind to; `taskId`/`runId` are filled once known (reserved
// for a future zero-flash in-place handoff — today the scene navigates to the detail page once the run exists).
export interface ActiveCreation {
    streamKey: string
    taskId?: string
    runId?: string
}

// `panelId` is set only by an embedded instance (e.g. Max's side panel runner), which mounts this logic
// under its own key rather than the scene's default singleton. Embedded instances stay in place on submit
// (no `/tasks/:id` navigation — the host renders the run from `activeCreation` itself) and ignore the scene's
// `urlToAction` cleanup (main-app navigation must never release a side panel's in-flight creation).
export interface TaskTrackerSceneLogicProps {
    panelId?: string
}

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
    props({} as TaskTrackerSceneLogicProps),
    // No `panelId` (the scene's own mount) resolves to the same 'scene' key every existing unbound
    // `useValues(taskTrackerSceneLogic)` / `taskTrackerSceneLogic.actions...` call site already relies on —
    // only an embedded caller that passes `panelId` gets its own instance.
    key((props) => props.panelId ?? 'scene'),

    connect(() => ({
        values: [tasksLogic, ['tasks', 'repositories', 'taskListParams'], integrationsLogic, ['integrations']],
        actions: [
            tasksLogic,
            ['loadTasks', 'loadRepositories', 'deleteTask'],
            integrationsLogic,
            ['loadIntegrationsSuccess'],
        ],
    })),

    actions({
        setNewTaskData: (data: Partial<TaskCreateForm>) => ({ data }),
        resetNewTaskData: true,
        submitNewTask: true,
        submitNewTaskSuccess: true,
        submitNewTaskFailure: (error: string) => ({ error }),
        maybeAutoSelectIntegration: true,
        setActiveSuggestionGroup: (group: SuggestionGroup | null) => ({ group }),
        applySuggestion: (item: SuggestionItem) => ({ item }),
        setHeadline: (headline: string) => ({ headline }),
        setPersistedRepositoryConfig: (config: PersistedRepositoryConfig) => ({ config }),
        setActiveCreation: (creation: ActiveCreation) => ({ creation }),
        clearActiveCreation: true,
        openExistingTask: (task: Task) => ({ task }),
        // Re-points the panel at a fresh run started from the composer on a reopened terminal task
        // (the run surface's own re-pointing targets the detail scene, which the panel doesn't render).
        updateActiveCreationRun: (runId: string) => ({ runId }),
        toggleHistory: true,
        setHistoryExpanded: (expanded: boolean) => ({ expanded }),
    }),

    reducers({
        newTaskData: [
            EMPTY_TASK_FORM as TaskCreateForm,
            {
                setNewTaskData: (state, { data }) => ({ ...state, ...data }),
                resetNewTaskData: () => EMPTY_TASK_FORM,
            },
        ],
        isSubmittingTask: [
            false,
            {
                submitNewTask: () => true,
                submitNewTaskSuccess: () => false,
                submitNewTaskFailure: () => false,
            },
        ],
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
                setNewTaskData: (state, { data }) =>
                    data.description !== undefined && !data.description ? null : state,
                resetNewTaskData: () => null,
            },
        ],
        headline: [
            DEFAULT_HEADLINES[0],
            {
                setHeadline: (_, { headline }) => headline,
            },
        ],
        // The in-flight optimistic create. While set (and no task is selected) the scene shows the pending
        // run thread instead of the composer.
        activeCreation: [
            null as ActiveCreation | null,
            {
                setActiveCreation: (_, { creation }) => creation,
                clearActiveCreation: () => null,
            },
        ],
        // Whether the panel is showing the full task history list instead of the composer/run. Reset
        // whenever a run takes over the panel, so returning to the composer never reopens stale history.
        historyExpanded: [
            false,
            {
                toggleHistory: (state) => !state,
                setHistoryExpanded: (_, { expanded }) => expanded,
                clearActiveCreation: () => false,
                openExistingTask: () => false,
            },
        ],
    }),

    selectors({
        sendDisabledReason: [
            (s) => [s.newTaskData],
            (newTaskData): string | undefined =>
                !newTaskData.description.trim() ? 'Describe the task first' : undefined,
        ],
    }),

    listeners(({ actions, values, cache, props }) => ({
        // Release the manually-mounted optimistic stream once the create resolves (navigated to the real run)
        // or fails (returned to the composer), so the throwaway draft instance never leaks.
        clearActiveCreation: () => {
            cache.activeCreationUnmount?.()
            cache.activeCreationUnmount = undefined
        },
        // Resetting the form (after a successful submit) wipes the repo selection; immediately re-derive it
        // (last persisted pick, else the first connected GitHub org) so the composer comes back with the
        // picker populated rather than blank.
        resetNewTaskData: () => {
            actions.maybeAutoSelectIntegration()
        },
        // Remember the repo/integration whenever the picker changes it to a real selection. Clearing the
        // repo ("No repo" option) is intentionally NOT persisted so the next visit restores the last good pick.
        setNewTaskData: ({ data }) => {
            if (data.repositoryConfig?.repository) {
                const { integrationId, repository } = data.repositoryConfig
                actions.setPersistedRepositoryConfig({ integrationId, repository })
            }
        },
        // Restore the remembered repo (or fall back to the first connected GitHub integration) when nothing is
        // chosen yet. The IntegrationChoice picker that used to own this selection is no longer rendered.
        maybeAutoSelectIntegration: () => {
            if (values.newTaskData.repositoryConfig.integrationId) {
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
                actions.setNewTaskData({ repositoryConfig: { integrationId, repository } })
                return
            }
            actions.setNewTaskData({
                repositoryConfig: {
                    ...values.newTaskData.repositoryConfig,
                    integrationId: githubIntegrations[0].id,
                },
            })
        },
        loadIntegrationsSuccess: () => {
            actions.maybeAutoSelectIntegration()
        },
        // Fill the composer with the suggestion; submit straight away unless it needs the user to finish
        // typing (the component focuses the textarea in that case).
        applySuggestion: ({ item }) => {
            actions.setNewTaskData({ description: item.content })
            if (!item.requiresUserInput) {
                actions.submitNewTask()
            }
        },
        submitNewTask: async () => {
            const { description, repositoryConfig, model, reasoningEffort } = values.newTaskData

            if (!description.trim()) {
                lemonToast.error('Description is required')
                actions.submitNewTaskFailure('Description is required')
                return
            }

            // Optimistically open the thread on send: a `runStreamLogic` keyed by a client `streamKey`, seeded
            // with the typed message + provisioning indicator, rendered by the pending `RunSurface` (the
            // composable optimistic-open primitive). Hold a manual mount so the seed is in place when the pending
            // pane renders, and survives across the React swap into the detail page (which adopts the same
            // instance by binding this `streamKey`). Released by `clearActiveCreation` (failure / leaving the run).
            cache.activeCreationUnmount?.()
            cache.activeCreationUnmount = undefined
            const streamKey = `draft-${uuid()}`
            const stream = runStreamLogic({ streamKey })
            cache.activeCreationUnmount = stream.mount()
            actions.setActiveCreation({ streamKey })
            stream.actions.startOptimisticRun(description)

            try {
                const taskData: TaskUpsertProps = {
                    title: '',
                    description,
                    origin_product: OriginProduct.POSTHOG_AI,
                    // PostHog AI can run without a repo; null means the task is not scoped to any repository.
                    repository: repositoryConfig.repository ?? null,
                    github_integration: repositoryConfig.integrationId ?? null,
                }

                const newTask = await api.tasks.create(taskData)

                // Auto-run the task after creation; the detail scene shows the latest run by default. The
                // run checks out the chosen branch (server falls back to the repo's default branch if unset)
                // and launches with the picked model / reasoning effort (clamped to one the model supports).
                const runResponse = await api.tasks.run(newTask.id, {
                    branch: repositoryConfig.branch ?? null,
                    runtime_adapter: ClaudeRuntimeAdapterEnumApi.Claude,
                    model,
                    reasoning_effort: resolveEffortForModel(reasoningEffort, model),
                    // Interactive keeps the sandbox agent-server's event stream open across turns, so
                    // follow-up messages stream their reply over the same SSE (background runs seal the
                    // stream after the first turn). Interactive runs boot with the agent-server pulling
                    // pending_user_message from run state (the workflow doesn't forward it), so seed the
                    // typed message as turn 1 — otherwise the first prompt is lost and the run idles.
                    mode: TaskExecutionModeEnumApi.Interactive,
                    pending_user_message: description,
                })

                // Attach the real ids to the optimistic creation so the detail page adopts this seeded stream
                // (same `streamKey` + real `runId`) instead of cold-bootstrapping a fresh, skeleton-flashing one.
                // Kept set across navigation; cleared by the `urlToAction` below once the user leaves this run.
                actions.setActiveCreation({ streamKey, taskId: newTask.id, runId: runResponse.latest_run?.id })
                // An embedded instance (`panelId` set) keeps the run in place — the host renders it from
                // `activeCreation` — rather than navigating the main app to the `/tasks/:id` detail page.
                if (!props.panelId) {
                    router.actions.push(`/tasks/${newTask.id}`)
                }

                actions.submitNewTaskSuccess()
                actions.resetNewTaskData()
                actions.loadTasks(values.taskListParams)
                actions.loadRepositories()
            } catch (error) {
                // Show the existing failure and return to the composer with the typed text intact.
                actions.clearActiveCreation()
                lemonToast.error('Failed to create task')
                actions.submitNewTaskFailure(error instanceof Error ? error.message : 'Unknown error')
            }
        },
        openExistingTask: ({ task }) => {
            if (task.latest_run) {
                // No optimistic stream seeding — the run surface bootstraps the thread from the API.
                actions.setActiveCreation({ streamKey: task.latest_run.id, taskId: task.id, runId: task.latest_run.id })
                return
            }
            // Never-ran task (rare for this panel's posthog_ai origin) — fall back to the full detail page.
            router.actions.push(`/tasks/${task.id}`)
        },
        updateActiveCreationRun: ({ runId }) => {
            if (!values.activeCreation?.taskId) {
                return
            }
            actions.setActiveCreation({ streamKey: runId, taskId: values.activeCreation.taskId, runId })
        },
    })),

    events(({ actions, values, cache }) => ({
        afterMount: () => {
            actions.loadTasks(values.taskListParams)
            actions.loadRepositories()
            // Roll a headline once per mount (pickHeadline forces index 0 under Storybook for stable snapshots).
            actions.setHeadline(pickHeadline())
            // integrationsLogic loads on its own mount (triggered by the connect above), so we don't call
            // loadIntegrations ourselves. loadIntegrationsSuccess covers that first load; this call covers
            // integrations already cached by an earlier mount.
            actions.maybeAutoSelectIntegration()
        },
        beforeUnmount: () => {
            // Release the manually-mounted optimistic stream if the whole scene unmounts mid-create — the
            // `clearActiveCreation` release only fires on navigation between runs, so leaving the tasks
            // scene entirely (before the creation resolves) would otherwise leak the mounted instance.
            cache.activeCreationUnmount?.()
            cache.activeCreationUnmount = undefined
        },
    })),

    urlToAction(({ actions, values, props }) => {
        // The optimistic creation is kept alive across the success navigation so the detail page can adopt
        // its seeded stream. Release it once the user lands anywhere other than the created task — another
        // task, the list, or back to `/tasks/new`. Guarded on `taskId` being set so the pre-id provisioning
        // phase (still at `/tasks/new`, no id yet) is never torn down mid-create.
        const clearIfLeftCreatedTask = (taskId?: string): void => {
            const activeCreation = values.activeCreation
            if (activeCreation?.taskId && activeCreation.taskId !== taskId) {
                actions.clearActiveCreation()
            }
        }
        return {
            // An embedded instance never navigates the main app on its own creation (see `submitNewTask`), so
            // main-app URL changes are unrelated to its run — never release the side panel's active creation.
            '/tasks': () => (props.panelId ? undefined : clearIfLeftCreatedTask()),
            '/tasks/:taskId': ({ taskId }) => (props.panelId ? undefined : clearIfLeftCreatedTask(taskId)),
        }
    }),
])
