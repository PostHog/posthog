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
import { isUUIDLike } from 'lib/utils/guards'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { LogEntry, parseLogEvent } from '../lib/parse-logs'
import { phDebugQueryParams, phDebugQuerySuffix } from '../lib/ph-debug'
import { TaskRun, TaskRunStatus } from '../types'
import type { taskDetailSceneLogicType } from './taskDetailSceneLogicType'
import { TaskLogicProps, taskLogic } from './taskLogic'
import { tasksLogic } from './tasksLogic'

const LOG_POLL_INTERVAL_MS = 1000
// The server rotates stream connections on a fixed cap (clean EOF + Last-Event-ID
// resume), so reconnect-after-EOF is a routine loop. If connections start dying
// this quickly, something is wrong server-side — stop hammering it and fall back
// to polling instead of reconnecting in a tight loop.
const STREAM_MIN_HEALTHY_CONNECTION_MS = 5000
const STREAM_MAX_CONSECUTIVE_SHORT_CONNECTIONS = 3

export type TaskDetailSceneLogicProps = TaskLogicProps

interface ParsedSseEvent {
    data: string
    eventType: string | null
    id: string | null
}

function buildToolMap(entries: LogEntry[]): Map<string, LogEntry> {
    const toolMap = new Map<string, LogEntry>()
    for (const entry of entries) {
        if (entry.type === 'tool' && entry.toolCallId) {
            toolMap.set(entry.toolCallId, { ...entry })
        }
    }
    return toolMap
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
        appendStreamEntries: (entries: LogEntry[]) => ({ entries }),
        updateStreamEntries: (entries: LogEntry[]) => ({ entries }),
        recordStreamProgress: (lastEventId: string) => ({ lastEventId }),
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
                appendStreamEntries: () => false,
            },
        ],
        runs: [
            [] as TaskRun[],
            {
                updateRun: (state: TaskRun[], { run }: { run: TaskRun }) =>
                    state.map((r) => (r.id === run.id ? run : r)),
            },
        ],
        streamEntries: [
            [] as LogEntry[],
            {
                setSelectedRunId: (state, { taskId }) => (taskId === props.taskId ? [] : state),
                appendStreamEntries: (state, { entries }) => {
                    if (entries.length === 0) {
                        return state
                    }
                    const last = state[state.length - 1]
                    const first = entries[0]
                    if (last?.type === first.type && (first.type === 'agent' || first.type === 'thinking')) {
                        return [
                            ...state.slice(0, -1),
                            { ...last, message: (last.message || '') + (first.message || '') },
                            ...entries.slice(1),
                        ]
                    }
                    return [...state, ...entries]
                },
                updateStreamEntries: (state, { entries }) => {
                    if (entries.length === 0) {
                        return state
                    }
                    const entriesById = new Map(entries.map((entry) => [entry.id, entry]))
                    let changed = false
                    const nextState = state.map((entry) => {
                        const updatedEntry = entriesById.get(entry.id)
                        if (!updatedEntry) {
                            return entry
                        }
                        changed = true
                        return updatedEntry
                    })
                    return changed ? nextState : state
                },
            },
        ],
        lastStreamEventId: [
            null as string | null,
            {
                setSelectedRunId: (state, { taskId }) => (taskId === props.taskId ? null : state),
                recordStreamProgress: (_, { lastEventId }) => lastEventId,
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
                    const runActive = run?.status === TaskRunStatus.QUEUED || run?.status === TaskRunStatus.IN_PROGRESS
                    // While live stream entries are rendered the log file isn't shown, so
                    // skip refetching it on every stream rotation. Once the run is terminal
                    // (or streaming has fallen back to polling) the fetch always happens —
                    // it backs the non-streaming fallback view; any tail a rotation cut off
                    // is recovered by the final drain connection in loadSelectedRunSuccess.
                    const streamRendersEntries = !values.streamingFailed && values.streamEntries.length > 0
                    if (!(runActive && streamRendersEntries)) {
                        // Use proxy endpoint to avoid CORS issues with direct S3 access
                        actions.loadLogs({
                            url: `/api/projects/${values.currentProjectId}/tasks/${props.taskId}/runs/${values.selectedRunId}/logs/${phDebugQuerySuffix()}`,
                        })
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
    }),

    listeners(({ actions, values, props, cache }) => ({
        setSelectedRunId: ({ taskId }) => {
            if (taskId !== props.taskId) {
                return
            }
            cache.seenStreamEventIds = new Set<string>()
            cache.consecutiveShortStreamConnections = 0
            cache.streamEndedWithRotation = false
            cache.finalDrainAttempted = false
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
        loadSelectedRunFailure: () => {
            // Stream rotation routes through loadSelectedRun (EOF → refresh → restart),
            // so a transient failure here must not strand the run view with neither
            // stream nor polling. Polling self-heals: the next successful load restarts
            // streaming or stops everything once the run is terminal. Gate on the last
            // loaded run still being active (shouldPoll) — a run that never loaded or
            // already finished must not arm a forever-retrying poll loop against a
            // permanently failing endpoint.
            if (values.shouldPoll && !values.isStreaming) {
                actions.startPolling()
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
                if (
                    cache.streamEndedWithRotation &&
                    !cache.finalDrainAttempted &&
                    !values.isStreaming &&
                    !values.streamingFailed &&
                    values.streamEntries.length > 0
                ) {
                    // The rotation EOF raced run completion: events published after the
                    // resume cursor would otherwise never render (streamEntries shadow the
                    // log file). One final drain connection delivers them, then normally
                    // EOFs via the completion sentinel — no rotation marker. But the
                    // sentinel is best-effort and can be missing, in which case the drain
                    // itself rotates and re-sets the flag; finalDrainAttempted makes the
                    // drain one-shot so a finished run can't re-drain in 15-minute cycles
                    // until the stream key expires.
                    cache.streamEndedWithRotation = false
                    cache.finalDrainAttempted = true
                    actions.startStreaming()
                } else {
                    actions.stopStreaming()
                }
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
                const toolMap = buildToolMap(values.streamEntries)
                let eventIndex = values.streamEntries.length
                // Dedupes events replayed across rotated connections. Lives in cache
                // (reset per selected run) so it survives reconnects without an O(n)
                // reducer copy per chunk batch on long runs.
                const seenStreamEventIds: Set<string> = (cache.seenStreamEventIds ??= new Set<string>())

                const consume = async (): Promise<void> => {
                    const connectionStartedAt = performance.now()
                    cache.streamEndedWithRotation = false
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

                            const batch: LogEntry[] = []
                            const updatedEntriesById = new Map<string, LogEntry>()
                            let lastProcessedEventId: string | null = null

                            for (const block of blocks) {
                                const parsedEvent = parseSseEventBlock(block)
                                if (parsedEvent?.eventType === 'end') {
                                    // `event: end` marks a connection-cap rotation, not run
                                    // completion — the EOF that follows triggers the restart.
                                    cache.streamEndedWithRotation = true
                                    continue
                                }
                                if (!parsedEvent || parsedEvent.eventType === 'keepalive' || !parsedEvent.data) {
                                    continue
                                }

                                if (parsedEvent.id) {
                                    if (seenStreamEventIds.has(parsedEvent.id)) {
                                        continue
                                    }
                                    seenStreamEventIds.add(parsedEvent.id)
                                    lastProcessedEventId = parsedEvent.id
                                }

                                try {
                                    const event = JSON.parse(parsedEvent.data) as Record<string, unknown>
                                    const entryId = parsedEvent.id
                                        ? `stream-${parsedEvent.id}`
                                        : `stream-${eventIndex++}`
                                    const entry = parseLogEvent(event, entryId, toolMap, (updatedEntry) => {
                                        updatedEntriesById.set(updatedEntry.id, updatedEntry)
                                    })
                                    if (entry) {
                                        // Merge consecutive agent/thinking messages
                                        const last = batch[batch.length - 1]
                                        if (
                                            last?.type === entry.type &&
                                            (entry.type === 'agent' || entry.type === 'thinking')
                                        ) {
                                            last.message = (last.message || '') + (entry.message || '')
                                        } else {
                                            batch.push(entry)
                                        }
                                    }
                                } catch {
                                    // Skip invalid JSON
                                }
                            }

                            if (lastProcessedEventId) {
                                actions.recordStreamProgress(lastProcessedEventId)
                            }
                            if (updatedEntriesById.size > 0) {
                                actions.updateStreamEntries(Array.from(updatedEntriesById.values()))
                            }
                            if (batch.length > 0) {
                                actions.appendStreamEntries(batch)
                            }
                        }

                        if (performance.now() - connectionStartedAt < STREAM_MIN_HEALTHY_CONNECTION_MS) {
                            cache.consecutiveShortStreamConnections = (cache.consecutiveShortStreamConnections ?? 0) + 1
                        } else {
                            cache.consecutiveShortStreamConnections = 0
                        }
                        // Clear streaming state before refreshing the run so in-progress
                        // runs can reconnect cleanly after an EOF.
                        actions.stopStreaming()
                        if (cache.consecutiveShortStreamConnections >= STREAM_MAX_CONSECUTIVE_SHORT_CONNECTIONS) {
                            console.warn('SSE stream ended immediately several times in a row, falling back to polling')
                            actions.markStreamingFailed()
                            actions.startPolling()
                            return
                        }
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
