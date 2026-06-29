import { actions, connect, events, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { tasksLogic } from '../../logics/tasksLogic'
import type { RepositoryConfig } from '../../types/taskTypes'
import { OriginProduct, TaskUpsertProps } from '../../types/taskTypes'
import type { taskTrackerSceneLogicType } from './taskTrackerSceneLogicType'

export type TaskCreateForm = {
    description: string
    repositoryConfig: RepositoryConfig
}

const EMPTY_TASK_FORM: TaskCreateForm = {
    description: '',
    repositoryConfig: {
        integrationId: undefined,
        repository: undefined,
    },
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
        setNewTaskData: (data: Partial<TaskCreateForm>) => ({ data }),
        resetNewTaskData: true,
        submitNewTask: true,
        submitNewTaskSuccess: true,
        submitNewTaskFailure: (error: string) => ({ error }),
        maybeAutoSelectIntegration: true,
    }),

    reducers({
        newTaskData: [
            EMPTY_TASK_FORM,
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
    }),

    listeners(({ actions, values }) => ({
        // IntegrationChoice used to auto-select the first integration of the kind; we no longer render it, so
        // the selection lives here. Picks the first connected GitHub integration when none is chosen yet.
        maybeAutoSelectIntegration: () => {
            if (values.newTaskData.repositoryConfig.integrationId) {
                return
            }
            const firstGithub = values.integrations?.find((integration) => integration.kind === 'github')
            if (firstGithub) {
                actions.setNewTaskData({
                    repositoryConfig: { ...values.newTaskData.repositoryConfig, integrationId: firstGithub.id },
                })
            }
        },
        loadIntegrationsSuccess: () => {
            actions.maybeAutoSelectIntegration()
        },
        submitNewTask: async () => {
            const { description, repositoryConfig } = values.newTaskData

            if (!description.trim()) {
                lemonToast.error('Description is required')
                actions.submitNewTaskFailure('Description is required')
                return
            }
            if (!repositoryConfig.integrationId || !repositoryConfig.repository) {
                lemonToast.error('Repository is required')
                actions.submitNewTaskFailure('Repository is required')
                return
            }

            try {
                const taskData: TaskUpsertProps = {
                    title: '',
                    description,
                    origin_product: OriginProduct.USER_CREATED,
                    repository: repositoryConfig.repository,
                    github_integration: repositoryConfig.integrationId ?? null,
                }

                const newTask = await api.tasks.create(taskData)
                lemonToast.success('Task created successfully')

                // Auto-run the task after creation; the detail scene shows the latest run by default. The
                // run checks out the chosen branch (server falls back to the repo's default branch if unset).
                await api.tasks.run(newTask.id, { branch: repositoryConfig.branch ?? null })
                router.actions.push(`/tasks/${newTask.id}`)

                actions.submitNewTaskSuccess()
                actions.resetNewTaskData()
                actions.loadTasks()
                actions.loadRepositories()
            } catch (error) {
                lemonToast.error('Failed to create task')
                actions.submitNewTaskFailure(error instanceof Error ? error.message : 'Unknown error')
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadTasks()
            actions.loadRepositories()
            // integrationsLogic loads on its own mount (triggered by the connect above), so we don't call
            // loadIntegrations ourselves. loadIntegrationsSuccess covers that first load; this call covers
            // integrations already cached by an earlier mount.
            actions.maybeAutoSelectIntegration()
        },
    })),
])
