import equal from 'fast-deep-equal'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Params } from 'scenes/sceneTypes'

import type { RepositoryConfig } from './components/RepositorySelector'
import type { tasksLogicType } from './tasksLogicType'
import { OriginProduct, Task, TaskRunStatus, TaskUpsertProps } from './types'

const DEFAULT_SEARCH_QUERY = ''
const DEFAULT_REPOSITORY = ''
const DEFAULT_STATUS = 'all'

export type TaskCreateForm = {
    title: string
    description: string
    repositoryConfig: RepositoryConfig
}

export const tasksLogic = kea<tasksLogicType>([
    path(['products', 'tasks', 'frontend', 'tasksLogic']),

    connect(() => ({
        values: [router, ['location']],
    })),

    actions({
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setRepository: (repository: string) => ({ repository }),
        setStatus: (status: 'all' | TaskRunStatus) => ({ status }),
        openTask: (taskId: Task['id']) => ({ taskId }),
        openCreateModal: true,
        closeCreateModal: true,
        setNewTaskData: (data: Partial<TaskCreateForm>) => ({ data }),
        resetNewTaskData: true,
        setValidationErrors: (errors: Record<string, string>) => ({ errors }),
        clearValidationError: (field: string) => ({ field }),
        submitNewTask: true,
        deleteTask: (taskId: Task['id']) => ({ taskId }),
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
        isCreateModalOpen: [
            false,
            {
                openCreateModal: () => true,
                closeCreateModal: () => false,
            },
        ],
        newTaskData: [
            {
                title: '',
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
                    title: '',
                    description: '',
                    repositoryConfig: {
                        integrationId: undefined,
                        organization: undefined,
                        repository: undefined,
                    },
                }),
            },
        ],
    }),

    loaders(({ values }) => ({
        tasks: [
            [] as Task[],
            {
                loadTasks: async () => {
                    const response = await api.tasks.list()
                    return response.results
                },
                submitNewTask: async () => {
                    const { title, description, repositoryConfig } = values.newTaskData

                    if (!title.trim()) {
                        throw new Error('Title is required')
                    }
                    if (
                        !repositoryConfig.integrationId ||
                        !repositoryConfig.organization ||
                        !repositoryConfig.repository
                    ) {
                        throw new Error('Repository is required')
                    }

                    const taskData: TaskUpsertProps = {
                        title,
                        description,
                        origin_product: OriginProduct.USER_CREATED,
                        repository: `${repositoryConfig.organization}/${repositoryConfig.repository}`,
                        github_integration: repositoryConfig.integrationId ?? null,
                    }

                    const newTask = await api.tasks.create(taskData)
                    lemonToast.success('Task created successfully')
                    router.actions.push(`/tasks/${newTask.id}`)
                    return [...values.tasks, newTask]
                },
                deleteTask: async ({ taskId }) => {
                    await api.tasks.delete(taskId)
                    lemonToast.success('Task deleted')
                    return values.tasks.filter((t) => t.id !== taskId)
                },
            },
        ],
    })),

    selectors({
        filteredTasks: [
            (s) => [s.tasks, s.searchQuery, s.repository, s.status],
            (tasks, searchQuery, repository, status): Task[] => {
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

                if (repository) {
                    filtered = filtered.filter((task) =>
                        task.repository.toLowerCase().includes(repository.toLowerCase())
                    )
                }

                if (status !== 'all') {
                    filtered = filtered.filter((task) => task.latest_run?.status === status)
                }

                filtered.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())

                return filtered
            },
        ],
        repositories: [
            (s) => [s.tasks],
            (tasks): string[] => {
                const repos = new Set(tasks.map((task) => task.repository))
                return Array.from(repos).sort()
            },
        ],
    }),

    listeners(({ actions }) => ({
        openTask: ({ taskId }) => {
            router.actions.push(`/tasks/${taskId}`)
        },
        submitNewTaskSuccess: () => {
            actions.resetNewTaskData()
            actions.closeCreateModal()
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

            return ['/tasks', params, {}, { replace: false }]
        }

        return {
            setSearchQuery: () => buildURL(),
            setRepository: () => buildURL(),
            setStatus: () => buildURL(),
        }
    }),

    afterMount(({ actions }) => {
        actions.loadTasks()
    }),
])
