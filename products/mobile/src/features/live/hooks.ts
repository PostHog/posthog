import { useIsFocused } from 'expo-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
    fetchLiveProject,
    fetchLiveQuery,
    fetchLiveStats,
    type LiveProjectApi,
    liveQuery,
    liveStatsHost,
    liveWindow,
} from '@/api/live'
import type { ProjectScope } from '@/api/reports'
import { addSessionEndTask } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useProjectScope } from '@/auth/useProjectScope'
import { type DataMode, useDataMode } from '@/demo/demoMode'
import { LIVE_DEMO_READ_MS, liveDemo } from '@/demo/live'
import { useAppActive } from '@/features/handoff/useTaskRun'
import { reportScopeError } from '@/features/views/useViewsAccess'
import { sleep } from '@/lib/sleep'
import { liveUsersOnlineFromQuery, liveUsersOnlineFromStats } from '@/model/adapters/live'
import { EMPTY_LIVE_SNAPSHOT, type LiveSnapshot } from '@/model/live'

import {
    type LiveErrorKind,
    trackLiveErrorShown,
    trackLivePaused,
    trackLiveRefreshed,
    trackLiveResumed,
} from './analytics'
import {
    LiveController,
    type LiveControllerEvent,
    type LiveControllerState,
    type LiveReadResult,
    type LiveSlowdown,
    type LiveStatus,
    liveStatus,
} from './liveController'
import { type LiveQueryRunner, readLiveSnapshot } from './liveRead'

/** The web's HogQL reload interval. */
const READ_INTERVAL_MS = 30_000
const STATS_INTERVAL_MS = 10_000
/** The Live chip reads users online alone, never the screen's full read, at the HogQL cadence. */
const CHIP_INTERVAL_MS = 30_000
const READ_SLOWDOWN: LiveSlowdown = { afterMs: 10 * 60_000, intervalMs: 60_000 }
const BACKGROUND_GRACE_MS = 2000
const MAX_BACKOFF_MS = 5 * 60_000
/** After this many failed stats reads in a row, users online comes from the HogQL count instead. */
const STATS_FAILURES_BEFORE_FALLBACK = 2

interface LiveProjectInfo {
    token: string | null
    pathCleaning: boolean
}

interface LiveSource {
    run: LiveQueryRunner
    project: () => Promise<LiveProjectInfo | null>
    /** The live events service for users online, or null when the HogQL count stands in for it. */
    statsHost: string | null
}

// The token lives for the session: the server mints it for a week, and a new sign-in clears this.
const projects = new Map<string, Promise<LiveProjectInfo | null>>()
addSessionEndTask(() => projects.clear())

function projectInfo(scope: ProjectScope): Promise<LiveProjectInfo | null> {
    const key = `${sessionGeneration()}|${scope.host}|${scope.projectId}`
    let pending = projects.get(key)
    if (!pending) {
        pending = fetchLiveProject().then(
            (project: LiveProjectApi) => ({
                token: project.live_events_token || null,
                pathCleaning: Array.isArray(project.path_cleaning_filters) && project.path_cleaning_filters.length > 0,
            }),
            () => {
                // A failed read is not kept, so the next visit asks again.
                projects.delete(key)
                return null
            }
        )
        projects.set(key, pending)
    }
    return pending
}

function sourceFor(mode: DataMode, scope: ProjectScope | null): LiveSource | null {
    if (mode === 'demo') {
        return {
            run: async (key, _query, signal, now) => {
                await sleep(LIVE_DEMO_READ_MS, signal)
                return liveDemo(now).respond(key, now)
            },
            project: () => Promise.resolve(null),
            statsHost: null,
        }
    }
    if (mode !== 'live' || !scope) {
        return null
    }
    return {
        run: async (_key, query, signal) => {
            try {
                return await fetchLiveQuery(query, signal)
            } catch (error) {
                reportScopeError(error, 'views')
                throw error
            }
        },
        project: () => projectInfo(scope),
        statsHost: liveStatsHost(scope.host),
    }
}

const INITIAL_STATE: LiveControllerState<never> = {
    data: null,
    updatedAt: null,
    paused: false,
    reading: false,
    failures: 0,
}

interface PollerOptions<T> {
    enabled: boolean
    read: (signal: AbortSignal, previous: T | null) => Promise<LiveReadResult<T>>
    intervalMs: number
    slowdown?: LiveSlowdown
    onEvent?: (event: LiveControllerEvent) => void
}

function usePoller<T>({ enabled, read, intervalMs, slowdown, onEvent }: PollerOptions<T>): {
    state: LiveControllerState<T>
    controller: LiveController<T> | null
    screenActive: boolean
} {
    const focused = useIsFocused()
    const active = useAppActive()
    const readRef = useRef(read)
    readRef.current = read
    const onEventRef = useRef(onEvent)
    onEventRef.current = onEvent
    const [controller, setController] = useState<LiveController<T> | null>(null)
    const [state, setState] = useState<LiveControllerState<T>>(INITIAL_STATE)
    useEffect(() => {
        if (!enabled) {
            return undefined
        }
        const next = new LiveController<T>({
            read: (signal, previous) => readRef.current(signal, previous),
            intervalMs,
            graceMs: BACKGROUND_GRACE_MS,
            maxBackoffMs: MAX_BACKOFF_MS,
            slowdown,
            onChange: setState,
            onEvent: (event) => onEventRef.current?.(event),
        })
        setController(next)
        return () => {
            next.dispose()
            setController(null)
            setState(INITIAL_STATE)
        }
    }, [enabled, intervalMs, slowdown])
    // The app state goes first, so a controller made in the background never reads before it knows.
    useEffect(() => controller?.setForeground(active), [controller, active])
    useEffect(() => controller?.setVisible(focused), [controller, focused])
    return { state, controller, screenActive: focused && active }
}

interface StatsUsersOnline {
    /** True while the live events service answers users online. */
    active: boolean
    /** True once the service cannot answer: another host, no token, or failed reads. The HogQL count stands in. */
    fallback: boolean
    count: number | null
    failed: boolean
    controller: LiveController<number | null> | null
}

/** Users online from the live events service on Cloud, every `intervalMs` while the screen is seen. */
function useStatsUsersOnline(source: LiveSource | null, intervalMs: number): StatsUsersOnline {
    // Kept with the source it came from, so a project switch never reads with the last project's token.
    const [known, setKnown] = useState<{ source: LiveSource; token: string | null } | null>(null)
    const [failedFor, setFailedFor] = useState<LiveSource | null>(null)
    const host = source?.statsHost ?? null
    // Undefined until the project read settles, so the HogQL count does not start while the token loads.
    const token = known !== null && known.source === source ? known.token : undefined
    const failed = source !== null && failedFor === source

    useEffect(() => {
        let cancelled = false
        if (source && host) {
            void source.project().then((info) => {
                if (!cancelled) {
                    setKnown({ source, token: info?.token ?? null })
                }
            })
        }
        return () => {
            cancelled = true
        }
    }, [source, host])

    const active = host !== null && typeof token === 'string' && !failed
    const read = useCallback(
        async (signal: AbortSignal): Promise<LiveReadResult<number | null>> => {
            if (!host || !token) {
                throw new Error('Live has no stats token.')
            }
            const count = liveUsersOnlineFromStats(await fetchLiveStats(host, token, signal))
            return { data: count, complete: count !== null }
        },
        [host, token]
    )
    const poller = usePoller<number | null>({ enabled: active, read, intervalMs })
    useEffect(() => {
        if (poller.state.failures >= STATS_FAILURES_BEFORE_FALLBACK) {
            setFailedFor(source)
        }
    }, [poller.state.failures, source])
    return {
        active,
        fallback: source !== null && (host === null || token === null || failed),
        count: active ? poller.state.data : null,
        failed: failed || (active && poller.state.failures > 0),
        controller: poller.controller,
    }
}

/**
 * Users online for the Live chip on the Web analytics screen. It reads only while that screen is focused and the app is
 * in the foreground.
 */
export function useLiveUsersOnline(): { count: number | null; reconnecting: boolean; screenActive: boolean } {
    const mode = useDataMode()
    const scope = useProjectScope()
    const source = useMemo(() => sourceFor(mode, scope), [mode, scope])
    const stats = useStatsUsersOnline(source, CHIP_INTERVAL_MS)
    const readCount = useCallback(
        async (signal: AbortSignal): Promise<LiveReadResult<number | null>> => {
            if (!source) {
                throw new Error('Live has no data source yet.')
            }
            const now = Date.now()
            const query = liveQuery('usersOnline', { window: liveWindow(now), pathCleaning: false })
            const count = liveUsersOnlineFromQuery(await source.run('usersOnline', query, signal, now))
            return { data: count, complete: count !== null }
        },
        [source]
    )
    const counted = usePoller<number | null>({
        enabled: stats.fallback,
        read: readCount,
        intervalMs: CHIP_INTERVAL_MS,
    })
    const reconnecting = stats.active
        ? stats.failed
        : counted.state.failures > 0 || (counted.state.data === null && stats.failed)
    const count = stats.active ? stats.count : counted.state.data
    return { count: reconnecting ? null : count, reconnecting, screenActive: counted.screenActive }
}

export interface LiveFeed {
    screenActive: boolean
    snapshot: LiveSnapshot
    status: LiveStatus
    updatedAt: number | null
    usersOnline: number | null
    paused: boolean
    reading: boolean
    loadFailed: boolean
    pulling: boolean
    pull: () => void
    pause: () => void
    resume: () => void
    retry: () => void
}

/**
 * Polls the live queries while the screen is focused and the app is in the foreground. Mount it only when the session
 * has access, keyed by the session and project identity.
 */
export function useLiveFeed(onError: (kind: LiveErrorKind) => void): LiveFeed {
    const mode = useDataMode()
    const scope = useProjectScope()
    const source = useMemo(() => sourceFor(mode, scope), [mode, scope])
    const stats = useStatsUsersOnline(source, STATS_INTERVAL_MS)
    const useStatsRef = useRef(stats.active)
    useStatsRef.current = stats.active

    const read = useCallback(
        async (signal: AbortSignal, previous: LiveSnapshot | null): Promise<LiveReadResult<LiveSnapshot>> => {
            if (!source) {
                throw new Error('Live has no data source yet.')
            }
            const project = await source.project()
            return readLiveSnapshot({
                run: source.run,
                previous: previous ?? EMPTY_LIVE_SNAPSHOT,
                countUsersOnline: !(source.statsHost !== null && project?.token && useStatsRef.current),
                pathCleaning: project?.pathCleaning ?? false,
                now: Date.now(),
                signal,
            })
        },
        [source]
    )
    const onEvent = useCallback((event: LiveControllerEvent) => {
        if (event === 'background_stopped') {
            trackLivePaused({ trigger: 'background' })
        } else {
            trackLiveResumed({ trigger: 'foreground' })
        }
    }, [])
    const main = usePoller<LiveSnapshot>({
        enabled: source !== null,
        read,
        intervalMs: READ_INTERVAL_MS,
        slowdown: READ_SLOWDOWN,
        onEvent,
    })

    const paused = main.state.paused
    useEffect(() => {
        if (paused) {
            stats.controller?.pause()
        } else {
            void stats.controller?.resume()
        }
    }, [paused, stats.controller])

    // One message per failure streak: when the first failed read follows data on screen, or the first load fails.
    const failing = main.state.failures > 0
    const hasData = main.state.data !== null
    const errorKind: LiveErrorKind | null = failing ? (hasData ? 'refresh_failed' : 'load_failed') : null
    const onErrorRef = useRef(onError)
    onErrorRef.current = onError
    useEffect(() => {
        if (errorKind) {
            trackLiveErrorShown({ kind: errorKind })
            onErrorRef.current(errorKind)
        }
    }, [errorKind])

    const [pulling, setPulling] = useState(false)
    const pull = useCallback(() => {
        trackLiveRefreshed({ trigger: 'pull' })
        setPulling(true)
        void Promise.all([main.controller?.refresh(), stats.controller?.refresh()]).finally(() => setPulling(false))
    }, [main.controller, stats.controller])
    const pause = useCallback(() => {
        trackLivePaused({ trigger: 'button' })
        main.controller?.pause()
    }, [main.controller])
    const resume = useCallback(() => {
        trackLiveResumed({ trigger: 'button' })
        trackLiveRefreshed({ trigger: 'resume' })
        void main.controller?.resume()
    }, [main.controller])
    const retry = useCallback(() => {
        void main.controller?.refresh()
    }, [main.controller])

    const snapshot = main.state.data ?? EMPTY_LIVE_SNAPSHOT
    return {
        screenActive: main.screenActive,
        snapshot,
        status: source ? liveStatus(main.state) : 'loading',
        updatedAt: main.state.updatedAt,
        usersOnline: stats.count ?? snapshot.usersOnline,
        paused,
        reading: main.state.reading,
        loadFailed: failing && !hasData,
        pulling,
        pull,
        pause,
        resume,
        retry,
    }
}
