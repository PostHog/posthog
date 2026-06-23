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

import api, { type EventSourceMessage } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isUUIDLike } from 'lib/utils/guards'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { tasksRunsStreamTokenRetrieve } from '../generated/api'
import { LogEntry, parseLogEvent } from '../lib/parse-logs'
import { phDebugQueryParams, phDebugQuerySuffix } from '../lib/ph-debug'
import { TaskRun, TaskRunStatus } from '../types'
import type { taskDetailSceneLogicType } from './taskDetailSceneLogicType'
import { TaskLogicProps, taskLogic } from './taskLogic'
import { tasksLogic } from './tasksLogic'

const LOG_POLL_INTERVAL_MS = 1000
// Reconnect the live stream a bounded number of times with exponential backoff
// before giving up. End-of-run is signalled in-band (the `stream-end` event), so
// a dropped connection always means "reconnect", never "the run is done".
const MAX_STREAM_RECONNECTS = 6
const STREAM_RECONNECT_BASE_MS = 1000
const STREAM_RECONNECT_MAX_MS = 15000
// A connection must stay open this long before a later drop earns a fresh reconnect
// budget. Resetting on every open would let a rapid open-and-die loop reconnect forever.
const STREAM_MIN_HEALTHY_CONNECTION_MS = 5000
// "Run is complete" terminal event. Named COMPLETE (not END) because connection-rotation
// work introduces a separate `end` event that means "reconnect", the opposite semantics.
const STREAM_COMPLETE_EVENT = 'stream-end'

export type TaskDetailSceneLogicProps = TaskLogicProps

function streamResumeStorageKey(runId: string): string {
    return `tasks:stream-resume:${runId}`
}

function readStreamResumeId(runId: string): string | null {
    try {
        return window.sessionStorage.getItem(streamResumeStorageKey(runId))
    } catch {
        return null
    }
}

function writeStreamResumeId(runId: string, eventId: string): void {
    try {
        window.sessionStorage.setItem(streamResumeStorageKey(runId), eventId)
    } catch {
        // sessionStorage may be unavailable (private mode / quota) — resume from in-memory state only
    }
}

function clearStreamResumeId(runId: string): void {
    try {
        window.sessionStorage.removeItem(streamResumeStorageKey(runId))
    } catch {
        // ignore
    }
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

interface StreamTarget {
    url: string
    headers: Record<string, string>
}

// Route the live stream through the standalone agent-proxy when the rollout flag is on AND the
// server resolves a base URL for it; otherwise hit the Django endpoint directly. The proxy is
// purely additive: if the token call fails (or the server returns no base URL), we fall back to
// the Django path, so streaming never breaks. With the flag off the token call is skipped
// entirely, keeping the pre-proxy request pattern unchanged.
async function resolveStreamTarget(taskId: string, runId: string, viaProxy: boolean): Promise<StreamTarget> {
    const djangoPath = `/api/projects/@current/tasks/${taskId}/runs/${runId}/stream/`
    if (!viaProxy) {
        return { url: djangoPath, headers: {} }
    }
    try {
        const { token, stream_base_url } = await tasksRunsStreamTokenRetrieve('@current', taskId, runId)
        if (!stream_base_url) {
            return { url: djangoPath, headers: {} }
        }
        // The proxy exposes a clean run-scoped path; the run-scoped token carries team and task.
        return {
            url: `${stream_base_url.replace(/\/+$/, '')}/v1/runs/${runId}/stream`,
            headers: { Authorization: `Bearer ${token}` },
        }
    } catch {
        return { url: djangoPath, headers: {} }
    }
}

export const taskDetailSceneLogic = kea<taskDetailSceneLogicType>([
    path(['products', 'tasks', 'taskDetailSceneLogic']),
    props({} as TaskDetailSceneLogicProps),
    key((props) => props.taskId),

    connect((props: TaskDetailSceneLogicProps) => ({
        values: [
            taskLogic(props),
            ['task', 'taskLoading'],
            teamLogic,
            ['currentProjectId'],
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['preflight'],
        ],
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
        markStreamComplete: true,
        appendStreamEntries: (entries: LogEntry[]) => ({ entries }),
        updateStreamEntries: (entries: LogEntry[]) => ({ entries }),
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
        streamComplete: [
            false,
            {
                setSelectedRunId: () => false,
                startStreaming: () => false,
                markStreamComplete: () => true,
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
        streamViaProxyEnabled: [
            (s) => [s.featureFlags, s.preflight],
            (featureFlags, preflight): boolean =>
                // Gates the durable-streaming rollout (stream_token + status-unaware streams). Local
                // dev disables the analytics SDK, so DEBUG instances opt in unconditionally — the
                // server still owns the final proxy-vs-Django decision via stream_token.
                !!featureFlags[FEATURE_FLAGS.TASKS_STREAM_VIA_PROXY] || !!preflight?.is_debug,
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
            if (values.streamComplete) {
                // The stream signalled end-of-run in-band; stop reopening it, but keep polling
                // until the refreshed run record catches up to a terminal status.
                actions.stopStreaming()
                const refreshedRun = selectedRunData ?? values.selectedRun
                if (
                    refreshedRun?.status === TaskRunStatus.QUEUED ||
                    refreshedRun?.status === TaskRunStatus.IN_PROGRESS
                ) {
                    actions.startPolling()
                } else {
                    actions.stopPolling()
                }
                return
            }
            if (values.streamingFailed) {
                // Reconnects were exhausted earlier; fall back to polling while the run is live,
                // and stop once it reaches a terminal status so the page doesn't poll forever.
                if (values.shouldPoll) {
                    actions.startPolling()
                } else {
                    actions.stopPolling()
                }
            } else if (!values.isStreaming) {
                if (values.streamViaProxyEnabled) {
                    // The durable stream is status-unaware: open it regardless of the run's current
                    // status and rely on the in-band stream-end sentinel to finish. Terminal runs
                    // replay their buffered events plus the sentinel; live runs stream as they go.
                    actions.startStreaming()
                } else if (values.shouldPoll) {
                    actions.startStreaming()
                } else {
                    // Rollout flag off: keep the pre-proxy behavior — terminal runs never open a
                    // stream connection.
                    actions.stopPolling()
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
            // Streaming replaces polling
            actions.stopPolling()

            const runId = values.selectedRunId
            if (!runId) {
                return
            }

            cache.disposables.add(() => {
                const abortController = new AbortController()
                const toolMap = buildToolMap(values.streamEntries)
                let eventIndex = values.streamEntries.length
                let reconnectCount = 0
                let tokenRefreshes = 0
                let openedAt = 0
                let terminated = false
                let disposed = false

                const handleDataEvent = (message: EventSourceMessage): void => {
                    if (message.id && values.seenStreamEventIds[message.id]) {
                        return
                    }
                    let event: Record<string, unknown>
                    try {
                        event = JSON.parse(message.data) as Record<string, unknown>
                    } catch {
                        return
                    }
                    const entryId = message.id ? `stream-${message.id}` : `stream-${eventIndex++}`
                    const entry = parseLogEvent(event, entryId, toolMap, (updatedEntry) => {
                        actions.updateStreamEntries([updatedEntry])
                    })
                    if (entry) {
                        // appendStreamEntries merges consecutive agent/thinking messages at the reducer level
                        actions.appendStreamEntries([entry])
                    }
                    if (message.id) {
                        actions.recordStreamProgress(message.id, [message.id])
                        writeStreamResumeId(runId, message.id)
                    }
                }

                const consume = async (): Promise<void> => {
                    // Resolve the stream target (agent-proxy when enabled, else Django) and seed the
                    // first connection from the persisted resume point; fetch-event-source manages
                    // Last-Event-ID across its own reconnects after that.
                    const target = await resolveStreamTarget(props.taskId, runId, values.streamViaProxyEnabled)
                    const resumeId = values.lastStreamEventId ?? readStreamResumeId(runId)
                    try {
                        await api.stream(target.url, {
                            method: 'GET',
                            signal: abortController.signal,
                            headers: { ...target.headers, ...(resumeId ? { 'Last-Event-ID': resumeId } : {}) },
                            onOpen: () => {
                                openedAt = Date.now()
                            },
                            onMessage: (message) => {
                                if (terminated) {
                                    return
                                }
                                if (message.event === STREAM_COMPLETE_EVENT) {
                                    terminated = true
                                    clearStreamResumeId(runId)
                                    actions.markStreamComplete()
                                    abortController.abort()
                                    return
                                }
                                if (message.event === 'error') {
                                    terminated = true
                                    abortController.abort()
                                    return
                                }
                                if (message.event === 'keepalive' || !message.data) {
                                    return
                                }
                                handleDataEvent(message)
                            },
                            onError: (error) => {
                                // fetch-event-source: returning a number reconnects after that
                                // many ms; throwing stops. A 4xx (run gone / forbidden) is fatal.
                                if (terminated || disposed) {
                                    throw error
                                }
                                // Only a connection that stayed healthy earns fresh budgets; this
                                // runs before the 4xx check so a mid-stream token expiry on a
                                // long-lived connection refreshes with a clean slate.
                                if (openedAt > 0 && Date.now() - openedAt >= STREAM_MIN_HEALTHY_CONNECTION_MS) {
                                    reconnectCount = 0
                                    tokenRefreshes = 0
                                }
                                openedAt = 0
                                const status = (error as { status?: number } | undefined)?.status
                                if (typeof status === 'number' && status >= 400 && status < 500) {
                                    throw error
                                }
                                reconnectCount += 1
                                if (reconnectCount > MAX_STREAM_RECONNECTS) {
                                    throw error
                                }
                                return Math.min(
                                    STREAM_RECONNECT_BASE_MS * 2 ** (reconnectCount - 1),
                                    STREAM_RECONNECT_MAX_MS
                                )
                            },
                            onClose: () => {
                                // Server closed the body without an end-of-run sentinel (e.g. a
                                // backend restart). Route through onError to reconnect; a genuine
                                // completion already set `terminated`.
                                if (terminated || disposed) {
                                    return
                                }
                                throw new Error('stream closed before completion')
                            },
                        })
                    } catch (error) {
                        // Stream read tokens are short-lived (the proxy validates them statelessly),
                        // so a reconnect on a long stream can outlive its token. On a 401 from the
                        // proxy leg, re-resolve the target — minting a fresh token re-checks access
                        // server-side — instead of giving up. Revoked users fail the re-resolve and
                        // land on the Django path, whose 4xx stays fatal.
                        const status = (error as { status?: number } | undefined)?.status
                        if (
                            !disposed &&
                            !terminated &&
                            status === 401 &&
                            target.headers.Authorization &&
                            tokenRefreshes < MAX_STREAM_RECONNECTS
                        ) {
                            tokenRefreshes += 1
                            return consume()
                        }
                        // Aborted, fatal, or reconnects exhausted — reconciled below
                    }

                    if (disposed) {
                        return
                    }
                    actions.stopStreaming()
                    if (!values.streamComplete) {
                        // Gave up only after real reconnect attempts (not the old one-error
                        // latch); fall back to polling. Resets when the run changes.
                        actions.markStreamingFailed()
                    }
                    actions.loadSelectedRun()
                }

                void consume()

                return () => {
                    disposed = true
                    abortController.abort()
                }
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
