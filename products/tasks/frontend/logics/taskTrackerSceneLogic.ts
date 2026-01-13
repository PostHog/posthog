import equal from 'fast-deep-equal'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Params } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import type { RepositoryConfig } from '../components/RepositorySelector'
import { OriginProduct, Task, TaskRunStatus, TaskUpsertProps } from '../types'
import type { taskTrackerSceneLogicType } from './taskTrackerSceneLogicType'
import { tasksLogic } from './tasksLogic'

const DEFAULT_SEARCH_QUERY = ''
const DEFAULT_REPOSITORY = 'all'
const DEFAULT_STATUS = 'all'

export type TaskCreateForm = {
    description: string
    repositoryConfig: RepositoryConfig
}

export const taskTrackerSceneLogic = kea<taskTrackerSceneLogicType>([
    path(['products', 'tasks', 'frontend', 'taskTrackerSceneLogic']),

    connect(() => ({
        values: [router, ['location'], userLogic, ['user'], tasksLogic, ['tasks']],
        actions: [tasksLogic, ['loadTasks', 'deleteTask']],
    })),

    actions({
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setRepository: (repository: string) => ({ repository }),
        setStatus: (status: 'all' | TaskRunStatus) => ({ status }),
        setCreatedBy: (createdBy: number | null) => ({ createdBy }),
        openCreateModal: true,
        closeCreateModal: true,
        setNewTaskData: (data: Partial<TaskCreateForm>) => ({ data }),
        resetNewTaskData: true,
        submitNewTask: true,
        submitNewTaskSuccess: true,
        submitNewTaskFailure: (error: string) => ({ error }),
        devOnlyInferTasks: true,
        devOnlyInferTasksSuccess: (message: string) => ({ message }),
        devOnlyInferTasksFailure: (error: string) => ({ error }),
    }),

    reducers({
        searchQuery: [
            DEFAULT_SEARCH_QUERY as string,
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        repository: [
            DEFAULT_REPOSITORY as string,
            {
                setRepository: (_, { repository }) => repository,
            },
        ],
        status: [
            DEFAULT_STATUS as 'all' | TaskRunStatus,
            {
                setStatus: (_, { status }) => status,
            },
        ],
        createdBy: [
            null as number | null,
            {
                setCreatedBy: (_, { createdBy }) => createdBy,
            },
        ],
        createdByInitialized: [
            false,
            {
                setCreatedBy: () => true,
                loadTasks: () => true,
            },
        ],
        isCreateModalOpen: [
            false,
            {
                openCreateModal: () => true,
                closeCreateModal: () => false,
            },
        ],
        newTaskData: [
            {
                description: '',
                repositoryConfig: {
                    integrationId: undefined,
                    organization: undefined,
                    repository: undefined,
                },
            } as TaskCreateForm,
            {
                setNewTaskData: (state, { data }) => ({ ...state, ...data }),
                resetNewTaskData: () => ({
                    description: '',
                    repositoryConfig: {
                        integrationId: undefined,
                        organization: undefined,
                        repository: undefined,
                    },
                }),
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
        isRunningClustering: [
            false,
            {
                devOnlyInferTasks: () => true,
                devOnlyInferTasksSuccess: () => false,
                devOnlyInferTasksFailure: () => false,
            },
        ],
    }),

    selectors({
        filteredTasks: [
            (s) => [s.tasks, s.searchQuery, s.repository, s.status, s.createdBy],
            (tasks, searchQuery, repository, status, createdBy): Task[] => {
                let filtered = [...tasks]

                if (searchQuery) {
                    const query = searchQuery.toLowerCase()
                    filtered = filtered.filter(
                        (task) =>
                            task.title.toLowerCase().includes(query) ||
                            task.description?.toLowerCase().includes(query) ||
                            task.slug.toLowerCase().includes(query)
                    )
                }

                if (repository && repository !== 'all') {
                    filtered = filtered.filter((task) =>
                        (task.repository ?? '').toLowerCase().includes(repository.toLowerCase())
                    )
                }

                if (status !== 'all') {
                    filtered = filtered.filter((task) => task.latest_run?.status === status)
                }

                if (createdBy !== null) {
                    filtered = filtered.filter((task) => task.created_by?.id === createdBy)
                }

                filtered.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

                return filtered
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        submitNewTask: async () => {
            const { description, repositoryConfig } = values.newTaskData

            if (!description.trim()) {
                lemonToast.error('Description is required')
                actions.submitNewTaskFailure('Description is required')
                return
            }
            if (!repositoryConfig.integrationId || !repositoryConfig.organization || !repositoryConfig.repository) {
                lemonToast.error('Repository is required')
                actions.submitNewTaskFailure('Repository is required')
                return
            }

            try {
                const taskData: TaskUpsertProps = {
                    title: '',
                    description,
                    origin_product: OriginProduct.USER_CREATED,
                    repository: `${repositoryConfig.organization}/${repositoryConfig.repository}`,
                    github_integration: repositoryConfig.integrationId ?? null,
                }

                const newTask = await api.tasks.create(taskData)
                lemonToast.success('Task created successfully')

                // Auto-run the task after creation
                const taskWithRun = await api.tasks.run(newTask.id)
                const runId = taskWithRun.latest_run?.id
                router.actions.push(`/tasks/${newTask.id}` + (runId ? `?runId=${runId}` : ''))

                actions.submitNewTaskSuccess()
                actions.resetNewTaskData()
                actions.closeCreateModal()
                actions.loadTasks()
            } catch (error) {
                lemonToast.error('Failed to create task')
                actions.submitNewTaskFailure(error instanceof Error ? error.message : 'Unknown error')
            }
        },
        devOnlyInferTasks: async () => {
            try {
                const response = await api.tasks.clusterVideoSegments()
                lemonToast.success(response.message || 'Clustering completed')
                actions.devOnlyInferTasksSuccess(response.message)
            } catch (error: any) {
                const errorMessage = error?.detail || error?.message || 'Failed to start clustering workflow'
                lemonToast.error(errorMessage)
                actions.devOnlyInferTasksFailure(errorMessage)
            }
        },
        devOnlyInferTasksSuccess: () => {
            // Clear user filter and reload tasks to show newly created clustered tasks
            actions.setCreatedBy(null)
            actions.loadTasks()
        },
    })),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (params.searchQuery && !equal(params.searchQuery, values.searchQuery)) {
                actions.setSearchQuery(params.searchQuery)
            }
            if (params.repository !== undefined && !equal(params.repository, values.repository)) {
                actions.setRepository(params.repository)
            }
            if (params.status && !equal(params.status, values.status)) {
                actions.setStatus(params.status)
            }
            if (params.createdBy !== undefined) {
                const createdByValue = params.createdBy ? parseInt(params.createdBy) : null
                if (!equal(createdByValue, values.createdBy)) {
                    actions.setCreatedBy(createdByValue)
                }
            }
        }
        return {
            '/tasks': urlToAction,
        }
    }),

    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            },
        ] => {
            const params: Params = {}

            if (values.searchQuery !== DEFAULT_SEARCH_QUERY) {
                params.searchQuery = values.searchQuery
            }
            if (values.repository !== DEFAULT_REPOSITORY) {
                params.repository = values.repository
            }
            if (values.status !== DEFAULT_STATUS) {
                params.status = values.status
            }
            if (values.createdBy !== null) {
                params.createdBy = values.createdBy.toString()
            }

            return ['/tasks', params, {}, { replace: false }]
        }

        return {
            setSearchQuery: () => buildURL(),
            setRepository: () => buildURL(),
            setStatus: () => buildURL(),
            setCreatedBy: () => buildURL(),
        }
    }),

    subscriptions(({ actions, values }) => ({
        user: (user) => {
            if (user?.id && !values.createdByInitialized) {
                actions.setCreatedBy(user.id)
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: [actions.loadTasks],
    })),
])
