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

import api from 'lib/api'

import { TaskRun, TaskRunStatus } from '../types'
import type { taskDetailSceneLogicType } from './taskDetailSceneLogicType'
import { TaskLogicProps, taskLogic } from './taskLogic'

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
        startLogPolling: true,
        stopLogPolling: true,
    }),

    reducers({
        selectedRunId: [
            null as TaskRun['id'] | null,
            {
                setSelectedRunId: (_, { runId }) => runId,
                loadRunsSuccess: (state, { runs }) => {
                    if (state) {
                        return state
                    }
                    return runs.length > 0 ? runs[0].id : null
                },
            },
        ],
    }),

    loaders(({ props, values }) => ({
        runs: [
            [] as TaskRun[],
            {
                loadRuns: async () => {
                    const response = await api.tasks.runs.list(props.taskId)
                    return response.results
                },
            },
        ],
        logs: [
            '' as string,
            {
                loadLogs: async ({ noCache }: { noCache?: boolean } = {}) => {
                    if (!values.selectedRunId) {
                        return ''
                    }
                    try {
                        return await api.tasks.runs.getLogs(props.taskId, values.selectedRunId, noCache ?? false)
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
            (s) => [s.runs, s.selectedRunId],
            (runs, selectedRunId): TaskRun | null => {
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
        shouldPollLogs: [
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
    }),

    listeners(({ actions, values }) => ({
        setSelectedRunId: () => {
            actions.stopLogPolling()
            actions.loadLogs()
            if (values.shouldPollLogs) {
                actions.startLogPolling()
            }
        },
        runTaskSuccess: () => {
            actions.loadRuns()
        },
        loadRunsSuccess: () => {
            if (values.selectedRunId) {
                actions.loadLogs()
            }
            if (values.shouldPollLogs) {
                actions.startLogPolling()
            } else {
                actions.stopLogPolling()
            }
        },
        startLogPolling: () => {
            if (logPollingInterval) {
                clearInterval(logPollingInterval)
            }
            logPollingInterval = window.setInterval(() => {
                actions.loadRuns()
                actions.loadLogs({ noCache: true })
            }, LOG_POLL_INTERVAL_MS)
        },
        stopLogPolling: () => {
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
        actions.stopLogPolling()
    }),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.taskId !== oldProps.taskId) {
            actions.stopLogPolling()
            actions.loadTask()
            actions.loadRuns()
        }
    }),
])
