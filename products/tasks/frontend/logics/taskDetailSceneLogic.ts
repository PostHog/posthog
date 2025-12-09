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
        startLogPolling: true,
        stopLogPolling: true,
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
            actions.selectLatestRun()
            actions.loadRuns()
        },
        loadRunsSuccess: ({ runs }) => {
            if (values.shouldSelectLatestRun && runs.length > 0) {
                actions.setSelectedRunId(runs[0].id)
            }
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

    urlToAction(({ actions, values }) => ({
        [urls.taskDetail(':taskId')]: (_, searchParams) => {
            const runIdFromUrl = searchParams.runId
            if (runIdFromUrl && runIdFromUrl !== values.selectedRunId) {
                actions.setSelectedRunId(runIdFromUrl)
            }
        },
    })),

    actionToUrl(({ values, props }) => ({
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
