import {
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { OriginProduct, TaskReference, TaskReferencesResponse, TaskRun, TaskRunStatus } from '../types'
import type { taskDetailSceneLogicType } from './taskDetailSceneLogicType'
import { TaskLogicProps, taskLogic } from './taskLogic'
import { tasksLogic } from './tasksLogic'

const LOG_POLL_INTERVAL_MS = 1000

export type TaskDetailSceneLogicProps = TaskLogicProps

let logPollingInterval: number | null = null

export const taskDetailSceneLogic = kea<taskDetailSceneLogicType>([
    path(['products', 'tasks', 'taskDetailSceneLogic']),
    props({} as TaskDetailSceneLogicProps),
    key((props) => props.taskId),

    connect((props: TaskDetailSceneLogicProps) => ({
        values: [taskLogic(props), ['task']],
        actions: [
            taskLogic(props),
            ['loadTask', 'loadTaskSuccess', 'runTask', 'runTaskSuccess', 'deleteTask', 'updateTask'],
        ],
    })),

    actions({
        setSelectedRunId: (runId: TaskRun['id'] | null, taskId: string) => ({ runId, taskId }),
        selectLatestRun: true,
        clearShouldSelectLatestRun: true,
        startPolling: true,
        stopPolling: true,
        setLogs: (logs: string) => ({ logs }),
        updateRun: (run: TaskRun) => ({ run }),
        // Reference actions
        setSelectedReference: (reference: TaskReference | null) => ({ reference }),
        loadMoreReferences: true,
    }),

    reducers(({ props }) => ({
        selectedRunId: [
            null as TaskRun['id'] | null,
            {
                setSelectedRunId: (state, { runId, taskId }) => (taskId === props.taskId ? runId : state),
            },
        ],
        shouldSelectLatestRun: [
            false,
            {
                selectLatestRun: () => true,
                clearShouldSelectLatestRun: () => false,
            },
        ],
        logs: [
            '' as string,
            {
                setSelectedRunId: (state, { taskId }) => (taskId === props.taskId ? '' : state),
                setLogs: (_, { logs }) => logs,
            },
        ],
        isInitialLogsLoad: [
            true as boolean,
            {
                setSelectedRunId: (state, { taskId }) => (taskId === props.taskId ? true : state),
                setLogs: () => false,
            },
        ],
        runs: [
            [] as TaskRun[],
            {
                updateRun: (state: TaskRun[], { run }: { run: TaskRun }) =>
                    state.map((r) => (r.id === run.id ? run : r)),
            },
        ],
        // Reference state
        selectedReference: [
            null as TaskReference | null,
            {
                setSelectedReference: (_, { reference }) => reference,
            },
        ],
        referencesOffset: [
            0,
            {
                loadReferencesSuccess: (state, { referencesResponse }) =>
                    state + (referencesResponse?.results.length ?? 0),
                loadMoreReferencesSuccess: (state, { referencesResponse }) =>
                    state + (referencesResponse?.results.length ?? 0),
            },
        ],
    })),

    loaders(({ props, values, actions }) => ({
        runs: [
            [] as TaskRun[],
            {
                loadRuns: async () => {
                    const response = await api.tasks.runs.list(props.taskId)
                    return response.results
                },
            },
        ],
        selectedRunData: [
            null as TaskRun | null,
            {
                loadSelectedRun: async () => {
                    if (!values.selectedRunId) {
                        return null
                    }
                    const run = await api.tasks.runs.get(props.taskId, values.selectedRunId)
                    // Use proxy endpoint to avoid CORS issues with direct S3 access
                    actions.loadLogs({
                        url: `/api/projects/@current/tasks/${props.taskId}/runs/${values.selectedRunId}/logs/`,
                    })
                    return run
                },
            },
        ],
        rawLogs: [
            '' as string,
            {
                loadLogs: async ({ url }: { url: string }) => {
                    try {
                        const response = await fetch(url, {
                            cache: 'no-store',
                            headers: { 'Cache-Control': 'no-cache' },
                        })
                        if (response.status === 404) {
                            return ''
                        }
                        if (!response.ok) {
                            console.error('Failed to load logs:', response.status, response.statusText)
                            return ''
                        }
                        return await response.text()
                    } catch (error) {
                        console.error('Failed to load logs:', error)
                        return ''
                    }
                },
            },
        ],
        referencesResponse: [
            null as TaskReferencesResponse | null,
            {
                loadReferences: async () => {
                    const response = await api.tasks.getReferences(props.taskId, 10, 0)
                    return response
                },
                loadMoreReferences: async () => {
                    const newResponse = await api.tasks.getReferences(props.taskId, 10, values.referencesOffset)
                    // Merge with existing results
                    const existingResults = values.referencesResponse?.results ?? []
                    return {
                        ...newResponse,
                        results: [...existingResults, ...newResponse.results],
                    }
                },
            },
        ],
    })),

    selectors({
        taskId: [() => [(_, props) => props.taskId], (taskId) => taskId],
        selectedRun: [
            (s) => [s.selectedRunData, s.runs, s.selectedRunId],
            (selectedRunData, runs, selectedRunId): TaskRun | null => {
                if (selectedRunData) {
                    return selectedRunData
                }
                if (!selectedRunId) {
                    return null
                }
                return runs.find((run) => run.id === selectedRunId) ?? null
            },
        ],
        canEditRepository: [
            (s) => [s.runs],
            (runs): boolean => {
                return runs.length === 0
            },
        ],
        shouldPoll: [
            (s) => [s.selectedRun],
            (selectedRun): boolean => {
                if (!selectedRun) {
                    return false
                }
                return selectedRun.status === TaskRunStatus.QUEUED || selectedRun.status === TaskRunStatus.IN_PROGRESS
            },
        ],
        title: [
            (s) => [s.task],
            (task): string => {
                return task?.title || task?.slug || 'Task'
            },
        ],
        logsLoading: [
            (s) => [s.rawLogsLoading, s.isInitialLogsLoad],
            (rawLogsLoading, isInitialLogsLoad): boolean => rawLogsLoading && isInitialLogsLoad,
        ],
        // Reference selectors
        isAutoGeneratedTask: [
            (s) => [s.task],
            (task): boolean => task?.origin_product === OriginProduct.SESSION_SUMMARIES,
        ],
        references: [(s) => [s.referencesResponse], (response): TaskReference[] => response?.results ?? []],
        referencesCount: [(s) => [s.referencesResponse], (response): number => response?.count ?? 0],
        hasMoreReferences: [
            (s) => [s.references, s.referencesCount],
            (references, count): boolean => references.length < count,
        ],
    }),

    listeners(({ actions, values, props }) => ({
        setSelectedRunId: ({ taskId }) => {
            if (taskId !== props.taskId) {
                return
            }
            actions.stopPolling()
            actions.loadSelectedRun()
        },
        runTaskSuccess: ({ task }) => {
            if (task?.id !== props.taskId) {
                return
            }
            if (task?.latest_run) {
                actions.setSelectedRunId(task.latest_run.id, props.taskId)
            }
            actions.loadRuns()
        },
        loadRunsSuccess: ({ runs }) => {
            const shouldSelect = values.shouldSelectLatestRun
            if (shouldSelect) {
                actions.clearShouldSelectLatestRun()
            }
            if (shouldSelect && runs.length > 0) {
                actions.setSelectedRunId(runs[0].id, props.taskId)
            } else if (values.selectedRunId) {
                actions.loadSelectedRun()
            }
        },
        loadSelectedRunSuccess: ({ selectedRunData }) => {
            if (selectedRunData) {
                actions.updateRun(selectedRunData)
            }
            actions.loadTask()
            if (values.shouldPoll) {
                actions.startPolling()
            } else {
                actions.stopPolling()
            }
        },
        loadTaskSuccess: ({ task }) => {
            if (task?.id !== props.taskId) {
                return
            }
            tasksLogic.findMounted()?.actions.updateTask(task)
            // Load references for auto-generated tasks
            if (task?.origin_product === OriginProduct.SESSION_SUMMARIES && !values.referencesResponse) {
                actions.loadReferences()
            }
        },
        loadLogsSuccess: ({ rawLogs }) => {
            if (rawLogs) {
                actions.setLogs(rawLogs)
            }
        },
        startPolling: () => {
            if (logPollingInterval) {
                clearInterval(logPollingInterval)
            }
            logPollingInterval = window.setInterval(() => {
                actions.loadSelectedRun()
            }, LOG_POLL_INTERVAL_MS)
        },
        stopPolling: () => {
            if (logPollingInterval) {
                clearInterval(logPollingInterval)
                logPollingInterval = null
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTask()
        actions.loadRuns()
    }),

    beforeUnmount(({ actions }) => {
        actions.stopPolling()
    }),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.taskId !== oldProps.taskId) {
            actions.stopPolling()
            actions.loadTask()
            actions.loadRuns()
        }
    }),

    urlToAction(({ actions, values, props }) => ({
        [urls.taskDetail(':taskId')]: (params, searchParams) => {
            const { taskId: urlTaskId } = params
            if (urlTaskId !== props.taskId) {
                return
            }
            const runIdFromUrl = searchParams.runId
            if (runIdFromUrl && runIdFromUrl !== values.selectedRunId) {
                actions.setSelectedRunId(runIdFromUrl, props.taskId)
            }
        },
    })),

    actionToUrl(({ props }) => ({
        setSelectedRunId: ({ runId }) => {
            if (runId) {
                return [urls.taskDetail(props.taskId), { runId }, router.values.hashParams]
            }
            return [urls.taskDetail(props.taskId), {}, router.values.hashParams]
        },
        loadRunsSuccess: ({ runs }) => {
            if (runs.length > 0 && !router.values.searchParams.runId) {
                return [urls.taskDetail(props.taskId), { runId: runs[0].id }, router.values.hashParams]
            }
            return undefined
        },
    })),
])
