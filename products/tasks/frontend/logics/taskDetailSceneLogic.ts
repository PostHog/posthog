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

import { TaskRun, TaskRunStatus } from '../types'
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
        values: [taskLogic(props), ['task', 'taskLoading']],
        actions: [taskLogic(props), ['loadTask', 'runTask', 'deleteTask', 'updateTask']],
    })),

    actions({
        setSelectedRunId: (runId: TaskRun['id'] | null) => ({ runId }),
        selectLatestRun: true,
        startPolling: true,
        stopPolling: true,
        setLogs: (logs: string) => ({ logs }),
    }),

    reducers({
        selectedRunId: [
            null as TaskRun['id'] | null,
            {
                setSelectedRunId: (_, { runId }) => runId,
            },
        ],
        shouldSelectLatestRun: [
            false,
            {
                selectLatestRun: () => true,
                loadRunsSuccess: () => false,
            },
        ],
        logs: [
            '' as string,
            {
                setSelectedRunId: () => '',
                setLogs: (_, { logs }) => logs,
            },
        ],
        isInitialLogsLoad: [
            true as boolean,
            {
                setSelectedRunId: () => true,
                setLogs: () => false,
            },
        ],
    }),

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
                    if (run.log_url) {
                        actions.loadLogs({ url: run.log_url })
                    }
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
                        return await response.text()
                    } catch (error) {
                        console.error('Failed to load logs:', error)
                        return ''
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
    }),

    listeners(({ actions, values }) => ({
        setSelectedRunId: () => {
            actions.stopPolling()
            actions.loadSelectedRun()
        },
        runTaskSuccess: () => {
            actions.selectLatestRun()
            actions.loadRuns()
        },
        loadRunsSuccess: ({ runs }) => {
            if (values.shouldSelectLatestRun && runs.length > 0) {
                actions.setSelectedRunId(runs[0].id)
            } else if (values.selectedRunId) {
                actions.loadSelectedRun()
            }
        },
        loadSelectedRunSuccess: ({ selectedRunData }) => {
            if (selectedRunData) {
                tasksLogic.findMounted()?.actions.updateTaskRun(props.taskId, selectedRunData)
            }
            if (values.shouldPoll) {
                actions.startPolling()
            } else {
                actions.stopPolling()
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

    urlToAction(({ actions, values }) => ({
        [urls.taskDetail(':taskId')]: (_, searchParams) => {
            const runIdFromUrl = searchParams.runId
            if (runIdFromUrl && runIdFromUrl !== values.selectedRunId) {
                actions.setSelectedRunId(runIdFromUrl)
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
