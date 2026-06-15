import equal from 'fast-deep-equal'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Params } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import type { RepositoryConfig } from '../components/RepositorySelector'
import { OriginProduct, TaskListParams, TaskRunStatus, TaskUpsertProps } from '../types'
import { tasksLogic } from './tasksLogic'
import type { taskTrackerSceneLogicType } from './taskTrackerSceneLogicType'

const DEFAULT_SEARCH_QUERY = ''
const DEFAULT_REPOSITORY = 'all'
const DEFAULT_STATUS: 'all' | TaskRunStatus = 'all'
const SEARCH_DEBOUNCE_MS = 300

export type TaskCreateForm = {
    description: string
    repositoryConfig: RepositoryConfig
}

export const taskTrackerSceneLogic = kea<taskTrackerSceneLogicType>([
    path(['products', 'tasks', 'frontend', 'taskTrackerSceneLogic']),

    connect(() => ({
        values: [router, ['location'], userLogic, ['user'], tasksLogic, ['tasks', 'repositories']],
        actions: [tasksLogic, ['loadTasks', 'loadRepositories', 'deleteTask']],
    })),

    actions({
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setRepository: (repository: string) => ({ repository }),
        setStatus: (status: 'all' | TaskRunStatus) => ({ status }),
        setCreatedBy: (createdBy: number | null) => ({ createdBy }),
        setShowInternal: (showInternal: boolean) => ({ showInternal }),
        openCreateModal: true,
        closeCreateModal: true,
        setNewTaskData: (data: Partial<TaskCreateForm>) => ({ data }),
        resetNewTaskData: true,
        submitNewTask: true,
        submitNewTaskSuccess: true,
        submitNewTaskFailure: (error: string) => ({ error }),
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
        showInternal: [
            false,
            {
                setShowInternal: (_, { showInternal }) => showInternal,
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
                    repository: undefined,
                },
            } as TaskCreateForm,
            {
                setNewTaskData: (state, { data }) => ({ ...state, ...data }),
                resetNewTaskData: () => ({
                    description: '',
                    repositoryConfig: {
                        integrationId: undefined,
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
    }),

    selectors({
        isStaff: [(s) => [s.user], (user): boolean => user?.is_staff ?? false],
        // All filters are pushed down to the backend via `loadTasks(listParams)` so results are
        // not limited by list pagination. The scene renders `tasks` (the loader output) directly.
        listParams: [
            (s) => [s.searchQuery, s.repository, s.status, s.createdBy, s.showInternal, s.isStaff],
            (searchQuery, repository, status, createdBy, showInternal, isStaff): TaskListParams => {
                const params: TaskListParams = {}
                if (searchQuery.trim()) {
                    params.search = searchQuery.trim()
                }
                if (repository && repository !== 'all') {
                    params.repository = repository
                }
                if (status !== 'all') {
                    params.status = status
                }
                if (createdBy !== null) {
                    params.created_by = createdBy
                }
                if (showInternal && isStaff) {
                    params.internal = true
                }
                return params
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        setSearchQuery: () => {
            cache.listLoadRequested = true
            // Debounce search keystrokes to avoid a request per character.
            if (cache.searchDebounce) {
                clearTimeout(cache.searchDebounce)
            }
            cache.searchDebounce = setTimeout(() => {
                actions.loadTasks(values.listParams)
            }, SEARCH_DEBOUNCE_MS)
        },
        setRepository: () => {
            cache.listLoadRequested = true
            actions.loadTasks(values.listParams)
        },
        setStatus: () => {
            cache.listLoadRequested = true
            actions.loadTasks(values.listParams)
        },
        setCreatedBy: () => {
            cache.listLoadRequested = true
            actions.loadTasks(values.listParams)
        },
        setShowInternal: () => {
            cache.listLoadRequested = true
            actions.loadTasks(values.listParams)
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

                // Auto-run the task after creation
                const taskWithRun = await api.tasks.run(newTask.id)
                const runId = taskWithRun.latest_run?.id
                router.actions.push(`/tasks/${newTask.id}` + (runId ? `?runId=${runId}` : ''))

                actions.submitNewTaskSuccess()
                actions.resetNewTaskData()
                actions.closeCreateModal()
                actions.loadTasks(values.listParams)
                actions.loadRepositories()
            } catch (error) {
                lemonToast.error('Failed to create task')
                actions.submitNewTaskFailure(error instanceof Error ? error.message : 'Unknown error')
            }
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
            if (params.showInternal !== undefined) {
                const showInternalValue = params.showInternal === 'true' || params.showInternal === true
                if (!equal(showInternalValue, values.showInternal)) {
                    actions.setShowInternal(showInternalValue)
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
            if (values.showInternal) {
                params.showInternal = 'true'
            }

            return ['/tasks', params, {}, { replace: false }]
        }

        return {
            setSearchQuery: () => buildURL(),
            setRepository: () => buildURL(),
            setStatus: () => buildURL(),
            setCreatedBy: () => buildURL(),
            setShowInternal: () => buildURL(),
        }
    }),

    subscriptions(({ actions, values }) => ({
        user: (user) => {
            if (user?.id && !values.createdByInitialized) {
                actions.setCreatedBy(user.id)
            }
        },
    })),

    events(({ actions, values, cache }) => ({
        afterMount: () => {
            actions.loadRepositories()
            // `urlToAction` may dispatch filter setters synchronously on mount, and the
            // `user` subscription may dispatch `setCreatedBy` to set the default filter.
            // Each of those listeners triggers `loadTasks` and sets `cache.listLoadRequested`,
            // so we only need to fire here when nothing else did.
            if (!cache.listLoadRequested) {
                actions.loadTasks(values.listParams)
            }
        },
        beforeUnmount: () => {
            if (cache.searchDebounce) {
                clearTimeout(cache.searchDebounce)
            }
            cache.listLoadRequested = false
        },
    })),
])
