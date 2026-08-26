import { MakeLogicType, actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { uuid } from 'lib/utils/dom'
import { projectLogic } from 'scenes/projectLogic'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'

import { tasksCreate, tasksRunCreate } from 'products/tasks/frontend/generated/api'
import {
    type ModelChoiceApi,
    OriginProductEnumApi,
    ReasoningEffortEnumApi,
    type TaskWriteApi,
    TaskExecutionModeEnumApi,
    type WarmTaskRequestApi,
    WarmTaskRequestOriginProductEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import type { IntegrationType, UserBasicType } from '../../../../../frontend/src/types'
import { attachedContextItemKey, attachedContextLogic, runStreamLogic } from '../../api/logics'
import type { SuggestionGroup, SuggestionItem } from '../../api/primitives'
import { DEFAULT_HEADLINES, pickHeadline } from '../../api/primitives'
import { composerSeedLogic } from '../../logics/composerSeedLogic'
import type { ComposerSeed } from '../../logics/composerSeedLogic'
import { modelCatalogueLogic } from '../../logics/modelCatalogueLogic'
import { runnerPanelLogic } from '../../logics/runnerPanelLogic'
import type { ActiveCreation } from '../../logics/runnerPanelLogic'
import { tasksLogic } from '../../logics/tasksLogic'
import { taskWarmLogic } from '../../logics/taskWarmLogic'
import type { WarmLease } from '../../logics/taskWarmLogic'
import { toolStreamEventsLogic } from '../../logics/toolStreamEventsLogic'
import { welcomeOverrideLogic } from '../../logics/welcomeOverrideLogic'
import type { AttachedContextItem } from '../../types/contextTypes'
import type { RepositoryConfig, Task } from '../../types/taskTypes'
import type { TaskListParams } from '../../types/taskTypes'
import {
    buildRunCreateRequest,
    DEFAULT_COMPOSER_EFFORT,
    DEFAULT_COMPOSER_MODEL,
    resolveEffortForModel,
} from '../../utils/composerModels'
import { DEFAULT_COMPOSER_MODE, type PermissionMode } from '../../utils/composerModes'
import { wrapWithPosthogContext } from '../../utils/posthogContextBlock'

export type { ActiveCreation } from '../../logics/runnerPanelLogic'

export interface TaskCreateForm {
    description: string
    repositoryConfig: RepositoryConfig
    model: string
    reasoningEffort: ReasoningEffortEnumApi
    permissionMode: PermissionMode
}

// The slice of the repo picker we remember across visits. Branch is deliberately excluded — on restore we
// want the branch picker to re-derive the repo's actual default branch (from the GitHub API), not pin a stale one.
export type PersistedRepositoryConfig = Pick<RepositoryConfig, 'integrationId' | 'repository'>

// `panelId` is set only by an embedded instance (e.g. Max's side panel runner), which mounts this logic
// under its own key rather than the scene's default singleton. Embedded instances stay in place on submit
// (no `/tasks/:id` navigation — the host renders the run from `activeCreation` itself) and ignore the scene's
// `urlToAction` cleanup (main-app navigation must never release a side panel's in-flight creation).
export interface TaskTrackerSceneLogicProps {
    panelId?: string
}

const LAST_REPOSITORY_CONFIG_STORAGE_KEY = 'posthog_ai.tasks.lastRepositoryConfig'

/**
 * The warm request for the current composer selection, or `null` when this selection can't be warmed.
 *
 * A repo-scoped warm must already know its branch: the backend matches branch as a `None`-normalized
 * exact value, so warming while `GitHubBranchCombobox` is still resolving the repo's default would
 * book a sandbox on `null` and then miss on submit. Repo-less drafts carry `null` on both sides and
 * warm immediately.
 */
function buildWarmRequest(form: TaskCreateForm, catalogue: ModelChoiceApi[]): WarmTaskRequestApi | null {
    const { repositoryConfig, model, reasoningEffort, permissionMode } = form
    if (repositoryConfig.repository && !repositoryConfig.branch) {
        return null
    }
    const runRequest = buildRunCreateRequest(
        catalogue,
        model,
        resolveEffortForModel(catalogue, reasoningEffort, model),
        permissionMode,
        { branch: repositoryConfig.branch ?? null }
    )
    if (!('runtime_adapter' in runRequest)) {
        return null
    }
    return {
        repository: repositoryConfig.repository ?? null,
        github_integration: repositoryConfig.integrationId ?? null,
        branch: runRequest.branch,
        runtime_adapter: runRequest.runtime_adapter,
        model: runRequest.model,
        reasoning_effort: runRequest.reasoning_effort,
        initial_permission_mode: runRequest.initial_permission_mode,
        origin_product: WarmTaskRequestOriginProductEnumApi.PosthogAi,
    }
}

const EMPTY_TASK_FORM: TaskCreateForm = {
    description: '',
    repositoryConfig: {
        integrationId: undefined,
        repository: undefined,
    },
    model: DEFAULT_COMPOSER_MODEL,
    reasoningEffort: DEFAULT_COMPOSER_EFFORT,
    permissionMode: DEFAULT_COMPOSER_MODE,
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface taskTrackerSceneLogicValues {
    dataProcessingAccepted: boolean // aiConsentLogic
    contextItems: AttachedContextItem[] // attachedContextLogic
    seed: ComposerSeed | null // composerSeedLogic
    integrations: IntegrationType[] | null // integrationsLogic
    catalogue: ModelChoiceApi[] // modelCatalogueLogic
    currentProjectId: number | null // projectLogic
    activeCreation: ActiveCreation | null // runnerPanelLogic
    historyExpanded: boolean // runnerPanelLogic
    warmLease: WarmLease | null // taskWarmLogic
    repositories: string[] // tasksLogic
    taskListParams: TaskListParams // tasksLogic
    tasks: Task[] // tasksLogic
    overrideHeadlines: string[] | null // welcomeOverrideLogic
    activeSuggestionGroup: SuggestionGroup | null
    consentBlocked: boolean
    displayHeadline: string
    headlineSeed: number
    isSubmittingTask: boolean
    newTaskData: TaskCreateForm
    persistedRepositoryConfig: PersistedRepositoryConfig
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface taskTrackerSceneLogicActions {
    markContextSent: (
        taskId: string,
        keys: string[]
    ) => {
        keys: string[]
        taskId: string
    } // attachedContextLogic
    consumeSeed: () => {
        value: true
    } // composerSeedLogic
    setSeed: (seed: ComposerSeed) => {
        seed: ComposerSeed
    } // composerSeedLogic
    loadIntegrationsSuccess: (
        integrations: {
            config: any
            created_at: string
            created_by?: UserBasicType | null | undefined
            display_name: string
            errors?: string | undefined
            icon_url: any
            id: number
            installation_shared?: boolean | null | undefined
            installation_status?:
                | null
                | import('products/integrations/frontend/generated/api.schemas').InstallationStatusEnumApi
                | undefined
            kind:
                | 'apns'
                | 'aws-s3'
                | 'azure-blob'
                | 'bing-ads'
                | 'clickup'
                | 'customerio-app'
                | 'customerio-track'
                | 'customerio-webhook'
                | 'databricks'
                | 'email'
                | 'firebase'
                | 'github'
                | 'gitlab'
                | 'google-ads'
                | 'google-analytics'
                | 'google-calendar'
                | 'google-cloud-service-account'
                | 'google-cloud-storage'
                | 'google-pubsub'
                | 'google-search-console'
                | 'google-sheets'
                | 'hubspot'
                | 'instagram'
                | 'intercom'
                | 'jira'
                | 'linear'
                | 'linkedin-ads'
                | 'meta-ads'
                | 'pardot'
                | 'pinterest-ads'
                | 'postgresql'
                | 'reddit-ads'
                | 's3-compatible'
                | 'salesforce'
                | 'slack'
                | 'snapchat'
                | 'snowflake'
                | 'stripe'
                | 'tiktok-ads'
                | 'twilio'
                | 'vercel'
                | 'youtube-analytics'
        }[],
        payload?: any
    ) => {
        integrations: {
            config: any
            created_at: string
            created_by?: UserBasicType | null | undefined
            display_name: string
            errors?: string | undefined
            icon_url: any
            id: number
            installation_shared?: boolean | null | undefined
            installation_status?:
                | null
                | import('products/integrations/frontend/generated/api.schemas').InstallationStatusEnumApi
                | undefined
            kind:
                | 'apns'
                | 'aws-s3'
                | 'azure-blob'
                | 'bing-ads'
                | 'clickup'
                | 'customerio-app'
                | 'customerio-track'
                | 'customerio-webhook'
                | 'databricks'
                | 'email'
                | 'firebase'
                | 'github'
                | 'gitlab'
                | 'google-ads'
                | 'google-analytics'
                | 'google-calendar'
                | 'google-cloud-service-account'
                | 'google-cloud-storage'
                | 'google-pubsub'
                | 'google-search-console'
                | 'google-sheets'
                | 'hubspot'
                | 'instagram'
                | 'intercom'
                | 'jira'
                | 'linear'
                | 'linkedin-ads'
                | 'meta-ads'
                | 'pardot'
                | 'pinterest-ads'
                | 'postgresql'
                | 'reddit-ads'
                | 's3-compatible'
                | 'salesforce'
                | 'slack'
                | 'snapchat'
                | 'snowflake'
                | 'stripe'
                | 'tiktok-ads'
                | 'twilio'
                | 'vercel'
                | 'youtube-analytics'
        }[]
        payload?: any
    } // integrationsLogic
    clearActiveCreation: () => {
        value: true
    } // runnerPanelLogic
    setActiveCreation: (creation: ActiveCreation) => {
        creation: ActiveCreation
    } // runnerPanelLogic
    setHistoryExpanded: (expanded: boolean) => {
        expanded: boolean
    } // runnerPanelLogic
    toggleHistory: () => {
        value: true
    } // runnerPanelLogic
    consumeWarm: () => {
        value: true
    } // taskWarmLogic
    noteDraft: (
        hasText: boolean,
        request: import('../../logics/taskWarmLogic').TaskWarmRequest
    ) => {
        hasText: boolean
        request: import('../../logics/taskWarmLogic').TaskWarmRequest
    } // taskWarmLogic
    releaseWarm: () => {
        value: true
    } // taskWarmLogic
    deleteTask: (args_0: { taskId: string }) => {
        taskId: string
    } // tasksLogic
    loadRepositories: () => any // tasksLogic
    loadTasks: (params?: TaskListParams | undefined) => TaskListParams // tasksLogic
    claimApplyBackTargets: (streamKey: string) => {
        streamKey: string
    } // toolStreamEventsLogic
    releaseApplyBackTargets: (streamKey: string) => {
        streamKey: string
    } // toolStreamEventsLogic
    applyComposerSeed: () => {
        value: true
    }
    applySuggestion: (item: SuggestionItem) => {
        item: SuggestionItem
    }
    blockOnConsent: () => {
        value: true
    }
    clearConsentBlock: () => {
        value: true
    }
    maybeAutoSelectIntegration: () => {
        value: true
    }
    openExistingTask: (task: Task) => {
        task: Task
    }
    resetNewTaskData: () => {
        value: true
    }
    setActiveSuggestionGroup: (group: SuggestionGroup | null) => {
        group: SuggestionGroup | null
    }
    setHeadlineSeed: (seed: number) => {
        seed: number
    }
    setNewTaskData: (data: Partial<TaskCreateForm>) => {
        data: Partial<TaskCreateForm>
    }
    setPersistedRepositoryConfig: (config: PersistedRepositoryConfig) => {
        config: PersistedRepositoryConfig
    }
    submitNewTask: () => {
        value: true
    }
    submitNewTaskFailure: (error: string) => {
        error: string
    }
    submitNewTaskSuccess: () => {
        value: true
    }
    updateActiveCreationRun: (runId: string) => {
        runId: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface taskTrackerSceneLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        displayHeadline: (overrideHeadlines: string[] | null, headlineSeed: number) => string
    }
}

export type taskTrackerSceneLogicType = MakeLogicType<
    taskTrackerSceneLogicValues,
    taskTrackerSceneLogicActions,
    TaskTrackerSceneLogicProps,
    taskTrackerSceneLogicMeta
>

export const taskTrackerSceneLogic = kea<taskTrackerSceneLogicType>([
    path(['products', 'posthog_ai', 'frontend', 'scenes', 'TaskTracker', 'taskTrackerSceneLogic']),
    props({} as TaskTrackerSceneLogicProps),
    // No `panelId` (the scene's own mount) resolves to the same 'scene' key every existing unbound
    // `useValues(taskTrackerSceneLogic)` / `taskTrackerSceneLogic.actions...` call site already relies on —
    // only an embedded caller that passes `panelId` gets its own instance.
    key((props) => props.panelId ?? 'scene'),

    connect((props: TaskTrackerSceneLogicProps) => ({
        values: [
            runnerPanelLogic(props),
            ['activeCreation', 'historyExpanded'],
            tasksLogic,
            ['tasks', 'repositories', 'taskListParams'],
            integrationsLogic,
            ['integrations'],
            attachedContextLogic,
            ['contextItems'],
            aiConsentLogic,
            ['dataProcessingAccepted'],
            projectLogic,
            ['currentProjectId'],
            composerSeedLogic(props),
            ['seed'],
            welcomeOverrideLogic,
            ['overrideHeadlines'],
            modelCatalogueLogic,
            ['catalogue'],
            // Only `panelId`: the scene is mounted with the `/tasks/:taskId` route param in its props, and
            // this composer always creates a fresh task, so a forwarded `taskId` would point the warm at
            // the resume endpoint for a task that doesn't exist yet.
            taskWarmLogic({ panelId: props.panelId }),
            ['warmLease'],
        ],
        actions: [
            runnerPanelLogic(props),
            ['setActiveCreation', 'clearActiveCreation', 'toggleHistory', 'setHistoryExpanded'],
            tasksLogic,
            ['loadTasks', 'loadRepositories', 'deleteTask'],
            integrationsLogic,
            ['loadIntegrationsSuccess'],
            attachedContextLogic,
            ['markContextSent'],
            toolStreamEventsLogic,
            ['claimApplyBackTargets', 'releaseApplyBackTargets'],
            composerSeedLogic(props),
            ['consumeSeed', 'setSeed'],
            taskWarmLogic({ panelId: props.panelId }),
            ['noteDraft', 'consumeWarm', 'releaseWarm'],
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
        setHeadlineSeed: (seed: number) => ({ seed }),
        setPersistedRepositoryConfig: (config: PersistedRepositoryConfig) => ({ config }),
        openExistingTask: (task: Task) => ({ task }),
        // Re-points the panel at a fresh run started from the composer on a reopened terminal task
        // (the run surface's own re-pointing targets the detail scene, which the panel doesn't render).
        updateActiveCreationRun: (runId: string) => ({ runId }),
        blockOnConsent: true,
        clearConsentBlock: true,
        // Pulls any pending `composerSeedLogic` seed into the composer (prefill + optional auto-submit).
        applyComposerSeed: true,
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
                blockOnConsent: () => false,
            },
        ],
        consentBlocked: [
            false,
            {
                blockOnConsent: () => true,
                clearConsentBlock: () => false,
                submitNewTask: () => false,
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
        headlineSeed: [
            0,
            {
                setHeadlineSeed: (_, { seed }) => seed,
            },
        ],
    }),

    selectors({
        // Contextual headlines registered by the active scene (welcomeOverrideLogic) win over the
        // generic defaults; the seed keeps the pick stable across re-renders.
        displayHeadline: [
            (s) => [s.overrideHeadlines, s.headlineSeed],
            (overrideHeadlines: string[] | null, headlineSeed: number): string =>
                pickHeadline(overrideHeadlines ?? DEFAULT_HEADLINES, headlineSeed),
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
            // Warm a sandbox while the user is still typing, so the submit lands on one that is already
            // up. `useDebouncedDraft` already coalesces keystrokes into this action, and `taskWarmLogic`
            // debounces again before it commits to a sandbox. Skipped while a run is being created —
            // that run is the desired state, not a warm.
            // Consent gates warming as it gates submitting (see `submitNewTask`): a warm boots a cloud
            // sandbox and clones the selected repository, so it must not run before the organization
            // accepts AI data processing.
            if (!values.activeCreation && values.dataProcessingAccepted) {
                const request = buildWarmRequest(values.newTaskData, values.catalogue)
                if (request) {
                    actions.noteDraft(values.newTaskData.description.trim().length > 0, request)
                }
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
            if (!values.dataProcessingAccepted) {
                actions.blockOnConsent()
                return
            }

            const { description, repositoryConfig, model, reasoningEffort, permissionMode } = values.newTaskData

            if (!description.trim()) {
                lemonToast.error('Description is required')
                actions.submitNewTaskFailure('Description is required')
                return
            }
            if (values.currentProjectId == null) {
                actions.submitNewTaskFailure('Project is required')
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
            const seededContext = values.contextItems
            actions.claimApplyBackTargets(streamKey)
            const stream = runStreamLogic({ streamKey })
            cache.activeCreationUnmount = stream.mount()
            actions.setActiveCreation({ streamKey })
            stream.actions.startOptimisticRun(description)

            try {
                const pendingUserMessage = wrapWithPosthogContext(description, seededContext)
                const runRequest = buildRunCreateRequest(
                    values.catalogue,
                    model,
                    resolveEffortForModel(values.catalogue, reasoningEffort, model),
                    permissionMode,
                    {
                        branch: repositoryConfig.branch ?? null,
                        mode: TaskExecutionModeEnumApi.Interactive,
                        pending_user_message: pendingUserMessage,
                    }
                )
                if (!('runtime_adapter' in runRequest)) {
                    throw new Error('Run request is missing a runtime adapter')
                }
                const taskData: TaskWriteApi = {
                    title: '',
                    description,
                    origin_product: OriginProductEnumApi.PosthogAi,
                    // PostHog AI can run without a repo; null means the task is not scoped to any repository.
                    repository: repositoryConfig.repository ?? null,
                    github_integration: repositoryConfig.integrationId ?? null,
                    // Warm-reuse hints. The backend matches these against an idling warm Run and, on a hit,
                    // activates it in place and returns it as `latest_run` — no second Run is created. All of
                    // them are write-only and ignored on a cold create. `branch` must be present as a key
                    // (even `null`) or reuse is never attempted at all.
                    branch: runRequest.branch ?? null,
                    runtime_adapter: runRequest.runtime_adapter,
                    model: runRequest.model,
                    reasoning_effort: runRequest.reasoning_effort,
                    initial_permission_mode: runRequest.initial_permission_mode,
                    pending_user_message: pendingUserMessage,
                }

                const projectId = String(values.currentProjectId)
                const newTask = await tasksCreate(projectId, taskData)
                // Whatever happened, this submit owns the warm now: drop the lease without cancelling it,
                // since the Run it points at is the one the create just activated.
                actions.consumeWarm()

                // `latest_run` set means the create matched an idling warm Run and activated it in place,
                // with `pending_user_message` as turn 1. Creating a second Run here would strand that warm
                // sandbox and cold-boot another one.
                //
                // Otherwise auto-run the task; the detail scene shows the latest run by default. The run
                // checks out the chosen branch (server falls back to the repo's default branch if unset)
                // and launches with the picked model / reasoning effort (clamped to one the model supports).
                let runId = newTask.latest_run?.id
                if (!runId) {
                    const runResponse = await tasksRunCreate(projectId, newTask.id, runRequest)
                    runId = runResponse.latest_run?.id
                }

                // Mark the seeded non-text refs sent under the created task, so the run's first follow-up
                // (sent via `runInteractionLogic`) doesn't re-wrap them. Text items always resend.
                const seededKeys = seededContext.filter((item) => item.type !== 'text').map(attachedContextItemKey)
                if (seededKeys.length > 0) {
                    actions.markContextSent(newTask.id, seededKeys)
                }

                // Attach the real ids to the optimistic creation so the detail page adopts this seeded stream
                // (same `streamKey` + real `runId`) instead of cold-bootstrapping a fresh, skeleton-flashing one.
                // Kept set across navigation; cleared by the `urlToAction` below once the user leaves this run.
                actions.setActiveCreation({ streamKey, taskId: newTask.id, runId })
                // An embedded instance (`panelId` set) keeps the run in place — the host renders it from
                // `activeCreation` — rather than navigating the main app to the `/tasks/:id` detail page.
                if (!props.panelId) {
                    router.actions.push(`/tasks/${newTask.id}`)
                }

                // Reset before signaling success: the success listener applies any seed held during this
                // submission, and resetting afterwards would wipe that seed's prefill.
                actions.resetNewTaskData()
                actions.submitNewTaskSuccess()
                actions.loadTasks(values.taskListParams)
                actions.loadRepositories()
            } catch (error) {
                actions.releaseApplyBackTargets(streamKey)
                // Return to the composer with the typed text intact, and no toast: the composer is
                // still on screen, so a failure banner over it reads as a dead end.
                actions.clearActiveCreation()
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
            // No `setActiveCreation` on this branch, so collapse history explicitly (the runnerPanelLogic
            // listener that normally does this only fires off that action).
            actions.setHistoryExpanded(false)
            router.actions.push(`/tasks/${task.id}`)
        },
        updateActiveCreationRun: ({ runId }) => {
            if (!values.activeCreation?.taskId) {
                return
            }
            actions.setActiveCreation({ streamKey: runId, taskId: values.activeCreation.taskId, runId })
        },
        // A seed arriving while this composer is already mounted (the panel was open when the host set it).
        // `setSeed` is connected from this instance's props-keyed seed logic — the bare `composerSeedLogic`
        // resolves to the default 'scene' key and would leave every embedded (panelId) instance deaf to its
        // own seeds. (A computed `composerSeedLogic(props).actionTypes.setSeed` key would work too, but the
        // call expression crashes kea-typegen once the seed logic's type file exists.)
        setSeed: () => {
            actions.applyComposerSeed()
        },
        applyComposerSeed: () => {
            const seed = values.seed
            if (!seed) {
                return
            }
            // A seed applied while a submit is in flight would start a second concurrent create/run (both
            // fighting over the composer and `activeCreation`), and the in-flight submit's success reset
            // would wipe a prefill. Leave it pending; the `submitNewTaskSuccess`/`Failure` listeners
            // re-apply it once the submission resolves, so the newest CTA still lands.
            if (values.isSubmittingTask) {
                return
            }
            // Consume-once: clear before applying so a re-entrant dispatch can't double-apply/submit.
            actions.consumeSeed()
            actions.setNewTaskData({ description: seed.prompt })
            if (seed.autoSubmit) {
                actions.submitNewTask()
            }
        },
        // Pick up a seed that was deliberately held while a submission was in flight (see `applyComposerSeed`).
        submitNewTaskSuccess: () => {
            actions.applyComposerSeed()
        },
        submitNewTaskFailure: () => {
            actions.applyComposerSeed()
        },
    })),

    events(({ actions, values, cache }) => ({
        afterMount: () => {
            actions.loadTasks(values.taskListParams)
            actions.loadRepositories()
            // Roll a headline seed once per mount (pickHeadline forces index 0 under Storybook for
            // stable snapshots regardless of seed).
            actions.setHeadlineSeed(Math.floor(Math.random() * 1000))
            // integrationsLogic loads on its own mount (triggered by the connect above), so we don't call
            // loadIntegrations ourselves. loadIntegrationsSuccess covers that first load; this call covers
            // integrations already cached by an earlier mount.
            actions.maybeAutoSelectIntegration()
            // A host commonly seeds the composer before this logic mounts (a CTA opens the panel, then the
            // panel mounts us), so pick up any pending seed now; the `setSeed` listener covers the reverse order.
            actions.applyComposerSeed()
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
