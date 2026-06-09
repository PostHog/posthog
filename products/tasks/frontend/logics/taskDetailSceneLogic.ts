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
import { isUUIDLike } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { AcpMessage } from '../conversation/acp-types'
import { parseSessionLogEvent, parseSessionLogs } from '../conversation/parseSessionLogs'
import { phDebugQueryParams, phDebugQuerySuffix } from '../lib/ph-debug'
import { TaskRun, TaskRunStatus } from '../types'
import type { taskDetailSceneLogicType } from './taskDetailSceneLogicType'
import { TaskLogicProps, taskLogic } from './taskLogic'
import { tasksLogic } from './tasksLogic'

const LOG_POLL_INTERVAL_MS = 1000

export type TaskDetailSceneLogicProps = TaskLogicProps

interface ParsedSseEvent {
    data: string
    eventType: string | null
    id: string | null
}

function parseSseEventBlock(block: string): ParsedSseEvent | null {
    let data = ''
    let eventType: string | null = null
    let id: string | null = null

    for (const line of block.split('\n')) {
        if (!line) {
            continue
        }
        if (line.startsWith(':')) {
            continue
        }
        if (line.startsWith('event:')) {
            eventType = line.slice(6).trim() || null
            continue
        }
        if (line.startsWith('id:')) {
            id = line.slice(3).trim() || null
            continue
        }
        if (line.startsWith('data:')) {
            data = data ? `${data}\n${line.slice(5).trimStart()}` : line.slice(5).trimStart()
        }
    }

    if (!data && !eventType && !id) {
        return null
    }

    return { data, eventType, id }
}

export const taskDetailSceneLogic = kea<taskDetailSceneLogicType>([
    path(['products', 'tasks', 'taskDetailSceneLogic']),
    props({} as TaskDetailSceneLogicProps),
    key((props) => props.taskId),

    connect((props: TaskDetailSceneLogicProps) => ({
        values: [taskLogic(props), ['task', 'taskLoading'], teamLogic, ['currentProjectId']],
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
        startStreaming: true,
        stopStreaming: true,
        markStreamingFailed: true,
        appendStreamEvents: (events: AcpMessage[]) => ({ events }),
        recordStreamProgress: (lastEventId: string | null, seenEventIds: string[]) => ({ lastEventId, seenEventIds }),
        setLogs: (logs: string) => ({ logs }),
        updateRun: (run: TaskRun) => ({ run }),
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
                appendStreamEvents: () => false,
            },
        ],
        runs: [
            [] as TaskRun[],
            {
                updateRun: (state: TaskRun[], { run }: { run: TaskRun }) =>
                    state.map((r) => (r.id === run.id ? run : r)),
            },
        ],
        streamEvents: [
            [] as AcpMessage[],
            {
                setSelectedRunId: (state, { taskId }) => (taskId === props.taskId ? [] : state),
                appendStreamEvents: (state, { events }) => {
                    if (events.length === 0) {
                        return state
                    }
                    // Raw ACP events are append-only; the conversation pipeline is
                    // responsible for merging consecutive message chunks and folding
                    // tool_call_update events into the originating tool call.
                    return [...state, ...events]
                },
            },
        ],
        lastStreamEventId: [
            null as string | null,
            {
                setSelectedRunId: (state, { taskId }) => (taskId === props.taskId ? null : state),
                recordStreamProgress: (state, { lastEventId }) => lastEventId ?? state,
            },
        ],
        seenStreamEventIds: [
            {} as Record<string, true>,
            {
                setSelectedRunId: (state, { taskId }) => (taskId === props.taskId ? {} : state),
                recordStreamProgress: (state, { seenEventIds }) => {
                    if (seenEventIds.length === 0) {
                        return state
                    }
                    return {
                        ...state,
                        ...Object.fromEntries(seenEventIds.map((eventId) => [eventId, true])),
                    }
                },
            },
        ],
        isStreaming: [
            false,
            {
                startStreaming: () => true,
                stopStreaming: () => false,
            },
        ],
        streamingFailed: [
            false,
            {
                setSelectedRunId: () => false,
                markStreamingFailed: () => true,
            },
        ],
    })),

    loaders(({ props, values, actions }) => ({
        runs: [
            [] as TaskRun[],
            {
                loadRuns: async () => {
                    const response = await api.tasks.runs.list(props.taskId, phDebugQueryParams())
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
                    const run = await api.tasks.runs.get(props.taskId, values.selectedRunId, phDebugQueryParams())
                    // Use proxy endpoint to avoid CORS issues with direct S3 access
                    actions.loadLogs({
                        url: `/api/projects/${values.currentProjectId}/tasks/${props.taskId}/runs/${values.selectedRunId}/logs/${phDebugQuerySuffix()}`,
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
        parsedLogEvents: [(s) => [s.logs], (logs): AcpMessage[] => parseSessionLogs(logs)],
        // Prefer live streamed events; fall back to the parsed S3 transcript when
        // no stream events have arrived yet (historical/replayed runs).
        events: [
            (s) => [s.streamEvents, s.parsedLogEvents],
            (streamEvents, parsedLogEvents): AcpMessage[] => (streamEvents.length > 0 ? streamEvents : parsedLogEvents),
        ],
    }),

    listeners(({ actions, values, props, cache }) => ({
        setSelectedRunId: ({ taskId }) => {
            if (taskId !== props.taskId) {
                return
            }
            actions.stopPolling()
            actions.stopStreaming()
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
                if (values.streamingFailed) {
                    actions.startPolling()
                } else if (!values.isStreaming) {
                    actions.startStreaming()
                }
            } else {
                actions.stopPolling()
                actions.stopStreaming()
            }
        },
        loadTaskSuccess: ({ task }) => {
            if (task?.id !== props.taskId) {
                return
            }
            tasksLogic.findMounted()?.actions.updateTask(task)
        },
        loadLogsSuccess: ({ rawLogs }) => {
            if (rawLogs) {
                actions.setLogs(rawLogs)
            }
        },
        startStreaming: () => {
            // Stop any existing polling — streaming replaces it
            actions.stopPolling()

            cache.disposables.add(() => {
                const abortController = new AbortController()
                const runId = values.selectedRunId
                if (!runId) {
                    return () => {}
                }

                // TODO(no-at-current-in-api-urls): migrate to `currentProjectIdStrict`. Rule misses this site because the URL is bound to a const and passed to fetch via the variable.
                const streamUrl = `/api/projects/@current/tasks/${props.taskId}/runs/${runId}/stream/`

                const consume = async (): Promise<void> => {
                    try {
                        const response = await fetch(streamUrl, {
                            signal: abortController.signal,
                            headers: {
                                Accept: 'text/event-stream',
                                ...(values.lastStreamEventId ? { 'Last-Event-ID': values.lastStreamEventId } : {}),
                            },
                        })

                        if (!response.ok || !response.body) {
                            // Stream not available — fall back to polling
                            actions.stopStreaming()
                            actions.markStreamingFailed()
                            actions.startPolling()
                            return
                        }

                        const reader = response.body.getReader()
                        const decoder = new TextDecoder()
                        let buffer = ''

                        while (true) {
                            const { done, value } = await reader.read()
                            if (done) {
                                break
                            }

                            buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
                            const blocks = buffer.split('\n\n')
                            buffer = blocks.pop() || ''

                            const batch: AcpMessage[] = []
                            let lastProcessedEventId: string | null = null
                            const newlySeenEventIds: string[] = []

                            for (const block of blocks) {
                                const parsedEvent = parseSseEventBlock(block)
                                if (!parsedEvent || parsedEvent.eventType === 'keepalive' || !parsedEvent.data) {
                                    continue
                                }

                                if (parsedEvent.id) {
                                    if (
                                        values.seenStreamEventIds[parsedEvent.id] ||
                                        newlySeenEventIds.includes(parsedEvent.id)
                                    ) {
                                        continue
                                    }
                                    newlySeenEventIds.push(parsedEvent.id)
                                    lastProcessedEventId = parsedEvent.id
                                }

                                try {
                                    const event = JSON.parse(parsedEvent.data) as Record<string, unknown>
                                    const message = parseSessionLogEvent(event)
                                    if (message) {
                                        batch.push(message)
                                    }
                                } catch {
                                    // Skip invalid JSON
                                }
                            }

                            if (newlySeenEventIds.length > 0) {
                                actions.recordStreamProgress(lastProcessedEventId, newlySeenEventIds)
                            }
                            if (batch.length > 0) {
                                actions.appendStreamEvents(batch)
                            }
                        }

                        // Clear streaming state before refreshing the run so in-progress
                        // runs can reconnect cleanly after an EOF.
                        actions.stopStreaming()
                        // Stream ended normally — do a final poll to get the latest run status
                        actions.loadSelectedRun()
                    } catch (e) {
                        if ((e as Error).name === 'AbortError') {
                            return
                        }
                        // Stream failed — fall back to polling
                        console.warn('SSE stream error, falling back to polling:', e)
                        actions.stopStreaming()
                        actions.markStreamingFailed()
                        actions.startPolling()
                    }
                }

                consume()

                return () => abortController.abort()
            }, 'sseStream')
        },
        stopStreaming: () => {
            cache.disposables.dispose('sseStream')
        },
        startPolling: () => {
            cache.disposables.add(() => {
                const intervalId = window.setInterval(() => {
                    actions.loadSelectedRun()
                }, LOG_POLL_INTERVAL_MS)
                return () => clearInterval(intervalId)
            }, 'logPolling')
        },
        stopPolling: () => {
            cache.disposables.dispose('logPolling')
        },
    })),

    afterMount(({ actions }) => {
        actions.loadTask()
        actions.loadRuns()
    }),

    beforeUnmount(({ actions }) => {
        actions.stopPolling()
        actions.stopStreaming()
    }),

    propsChanged(({ actions, props }, oldProps) => {
        if (props.taskId !== oldProps.taskId) {
            actions.stopPolling()
            actions.stopStreaming()
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
            if (runIdFromUrl && isUUIDLike(runIdFromUrl) && runIdFromUrl !== values.selectedRunId) {
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
