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
import { LIVE_DEMO_READ_MS, liveDemo, liveDemoState } from '@/demo/live'
import { useAppActive } from '@/features/handoff/useTaskRun'
import { reportScopeError } from '@/features/views/useViewsAccess'
import { sleep } from '@/lib/sleep'
import { useDelayedReconnecting } from '@/lib/useDelayedReconnecting'
import { liveProjectState, liveUsersOnlineFromQuery, liveUsersOnlineFromStats } from '@/model/adapters/live'
import {
    EMPTY_LIVE_SNAPSHOT,
    type LiveMobileMetrics,
    type LiveProjectState,
    type LiveSnapshot,
    type LiveWorld,
} from '@/model/live'

import {
    type LiveErrorKind,
    trackLiveErrorShown,
    trackLivePaused,
    trackLiveRefreshed,
    trackLiveResumed,
    trackLiveStateShown,
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
import { useLivePreference } from './livePreference'
import { type LiveQueryRunner, liveMobileMetrics, readLiveSnapshot, readLiveWorld } from './liveRead'
import { readSlowLiveQuery } from './liveSlowQuery'
import { useLiveWorldShare } from './liveWorldStore'

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
const PROJECT_RECHECK_MS = 60_000

interface LiveProjectInfo {
    token: string | null
    pathCleaning: boolean
    /** False until the project ingests its first event. Null when the response does not say. */
    ingestedEvent: boolean | null
}

interface LiveSource {
    run: LiveQueryRunner
    /** The project read of this session, or a new one when the last is at least `maxAgeMs` old. */
    project: (maxAgeMs?: number) => Promise<LiveProjectInfo | null>
    /** The live events service for users online, or null when the HogQL count stands in for it. */
    statsHost: string | null
}

interface ProjectRead {
    pending: Promise<LiveProjectInfo | null>
    /** When the read started, epoch milliseconds. */
    at: number
}

// The token lives for the session: the server mints it for a week, and a new sign-in clears this.
const projects = new Map<string, ProjectRead>()
addSessionEndTask(() => projects.clear())

function projectInfoFrom(project: LiveProjectApi): LiveProjectInfo {
    return {
        token: project.live_events_token || null,
        pathCleaning: Array.isArray(project.path_cleaning_filters) && project.path_cleaning_filters.length > 0,
        ingestedEvent: typeof project.ingested_event === 'boolean' ? project.ingested_event : null,
    }
}

function projectInfo(scope: ProjectScope, maxAgeMs = Number.POSITIVE_INFINITY): Promise<LiveProjectInfo | null> {
    const key = `${sessionGeneration()}|${scope.host}|${scope.projectId}`
    const cached = projects.get(key)
    if (cached && Date.now() - cached.at < maxAgeMs) {
        return cached.pending
    }
    const kept = cached?.pending
    const read: ProjectRead = {
        at: Date.now(),
        pending: fetchLiveProject(undefined, scope).then(projectInfoFrom, () => {
            // A failed first read is not kept, so the next visit asks again. A failed read after a good one keeps
            // the good answer with this read's start time, so a project that keeps failing is read at most once a
            // `maxAgeMs`.
            if (projects.get(key) === read) {
                if (kept) {
                    projects.set(key, { pending: kept, at: read.at })
                } else {
                    projects.delete(key)
                }
            }
            return kept ?? Promise.resolve(null)
        }),
    }
    projects.set(key, read)
    return read.pending
}

function sourceFor(
    mode: DataMode,
    scope: ProjectScope | null,
    preference: 'all' | 'web' | 'mobile' = 'all'
): LiveSource | null {
    if (mode === 'demo') {
        const fixture = liveDemoState()
        const state =
            preference === 'mobile'
                ? 'app_only'
                : preference === 'web'
                  ? 'web'
                  : fixture === 'quiet' || fixture === 'not_set_up'
                    ? fixture
                    : 'mixed'
        const project: LiveProjectInfo = { token: null, pathCleaning: false, ingestedEvent: state !== 'not_set_up' }
        return {
            run: async (key, _query, signal, now) => {
                await sleep(LIVE_DEMO_READ_MS, signal)
                return liveDemo(now, state).respond(key, now)
            },
            project: () => Promise.resolve(project),
            statsHost: null,
        }
    }
    if (mode !== 'live' || !scope) {
        return null
    }
    return {
        run: async (_key, query, signal) => {
            try {
                if (_key === 'mobileMetrics') {
                    const key = `${sessionGeneration()}|${scope.host}|${scope.projectId}`
                    return await readSlowLiveQuery(key, Date.now(), () => fetchLiveQuery(query, signal, scope))
                }
                return await fetchLiveQuery(query, signal, scope)
            } catch (error) {
                reportScopeError(error, 'views')
                throw error
            }
        },
        project: (maxAgeMs) => projectInfo(scope, maxAgeMs),
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
    /** True when the live events service can count users online for this project, also while its read waits. */
    active: boolean
    /** True once the service cannot answer: another host, no token, or failed reads. The HogQL count stands in. */
    fallback: boolean
    count: number | null
    failed: boolean
    controller: LiveController<number | null> | null
}

/**
 * Users online from the live events service on Cloud, every `intervalMs` while the screen is seen and `enabled` is
 * true. `project` is the project read, undefined while it loads, so the HogQL count does not start while the token
 * loads.
 */
function useStatsUsersOnline(
    source: LiveSource | null,
    intervalMs: number,
    project: LiveProjectInfo | null | undefined,
    enabled = true,
    allowed = true
): StatsUsersOnline {
    const [failedFor, setFailedFor] = useState<LiveSource | null>(null)
    const host = source?.statsHost ?? null
    const token = project === undefined ? undefined : (project?.token ?? null)
    const failed = source !== null && failedFor === source

    const active = allowed && host !== null && typeof token === 'string' && !failed
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
    const poller = usePoller<number | null>({ enabled: active && enabled, read, intervalMs })
    useEffect(() => {
        if (poller.state.failures >= STATS_FAILURES_BEFORE_FALLBACK) {
            setFailedFor(source)
        }
    }, [poller.state.failures, source])
    return {
        active,
        fallback: source !== null && (!allowed || host === null || token === null || failed),
        count: active ? poller.state.data : null,
        failed: failed || (active && poller.state.failures > 0),
        controller: poller.controller,
    }
}

interface LiveProjectRead {
    /** Undefined until the first project read settles. Null when it failed. */
    info: LiveProjectInfo | null | undefined
    /** Reads the project again when the last read is at least `maxAgeMs` old. */
    recheck: (maxAgeMs: number) => Promise<void>
}

function useLiveProject(source: LiveSource | null): LiveProjectRead {
    // Kept with the source it came from, so a project switch never shows the last project's state.
    const [known, setKnown] = useState<{ source: LiveSource; info: LiveProjectInfo | null } | null>(null)
    useEffect(() => {
        let cancelled = false
        if (source) {
            void source.project().then((info) => {
                if (!cancelled) {
                    setKnown({ source, info })
                }
            })
        }
        return () => {
            cancelled = true
        }
    }, [source])
    const recheck = useCallback(
        async (maxAgeMs: number): Promise<void> => {
            if (!source) {
                return
            }
            const info = await source.project(maxAgeMs)
            setKnown((current) => (current?.source === source ? { source, info } : current))
        },
        [source]
    )
    return { info: known?.source === source ? known.info : undefined, recheck }
}

/**
 * Users online for the Live chip on the Web analytics screen. It reads only while that screen is focused and the app is
 * in the foreground.
 */
export function useLiveUsersOnline(): { count: number | null; reconnecting: boolean; screenActive: boolean } {
    const mode = useDataMode()
    const scope = useProjectScope()
    const source = useMemo(() => sourceFor(mode, scope), [mode, scope])
    const project = useLiveProject(source)
    const stats = useStatsUsersOnline(source, CHIP_INTERVAL_MS, project.info)
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
    const reconnecting = useDelayedReconnecting(
        counted.screenActive &&
            (stats.active ? stats.failed : counted.state.failures > 0 || (counted.state.data === null && stats.failed)),
        source,
        async (): Promise<void> => {
            await (stats.active ? stats.controller : counted.controller)?.checkRecovery()
        }
    )
    const count = stats.active ? stats.count : counted.state.data
    const [lastCount, setLastCount] = useState<{ source: LiveSource | null; count: number } | null>(null)
    useEffect(() => {
        if (count !== null) setLastCount({ source, count })
    }, [source, count])
    return {
        count: reconnecting ? null : (count ?? (lastCount?.source === source ? lastCount.count : null)),
        reconnecting,
        screenActive: counted.screenActive,
    }
}

/** `mobile_live_state_shown` once per focus for each state other than `web`. */
function useLiveStateShown(state: LiveProjectState | null): void {
    const focused = useIsFocused()
    const shown = useRef(new Set<LiveProjectState>())
    useEffect(() => {
        if (!focused) {
            shown.current.clear()
        } else if (state && state !== 'web' && !shown.current.has(state)) {
            shown.current.add(state)
            trackLiveStateShown({ state })
        }
    }, [focused, state])
}

export interface LiveFeed {
    screenActive: boolean
    snapshot: LiveSnapshot
    /** Null until the project read settles. */
    state: LiveProjectState | null
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

function useMobileMetrics(
    source: LiveSource | null,
    enabled: boolean
): ReturnType<typeof usePoller<LiveMobileMetrics>> {
    const read = useCallback(
        async (signal: AbortSignal): Promise<LiveReadResult<LiveMobileMetrics>> => {
            if (!source) throw new Error('Live has no data source yet.')
            const now = Date.now()
            const query = liveQuery('mobileMetrics', { window: liveWindow(now), pathCleaning: false })
            const answer = await source.run('mobileMetrics', query, signal, now)
            return { data: liveMobileMetrics(answer, now), complete: true }
        },
        [source]
    )
    return usePoller({ enabled, read, intervalMs: PROJECT_RECHECK_MS })
}

/**
 * Polls the live queries while the screen is focused and the app is in the foreground. Mount it only when the session
 * has access, keyed by the session and project identity.
 *
 * A project that has never sent an event runs no live reads. While the screen is seen, Live reads the project again
 * every minute and on focus and foreground, at most once a minute, and starts polling once the project has an event.
 */
export function useLiveFeed(onError: (kind: LiveErrorKind) => void): LiveFeed {
    const { preference } = useLivePreference()
    const mode = useDataMode()
    const scope = useProjectScope()
    const source = useMemo(() => sourceFor(mode, scope), [mode, scope])
    const project = useLiveProject(source)
    const notSetUp = project.info?.ingestedEvent === false
    const statsActive = useRef(false)
    const completedPreference = useRef<string | null>(null)

    const read = useCallback(
        async (signal: AbortSignal, previous: LiveSnapshot | null): Promise<LiveReadResult<LiveSnapshot>> => {
            if (!source) {
                throw new Error('Live has no data source yet.')
            }
            const info = await source.project()
            const profile = {
                kind:
                    preference === 'all'
                        ? mode === 'demo' && liveDemoState() === 'quiet'
                            ? ('web' as const)
                            : ('mixed' as const)
                        : preference,
            }
            const result = await readLiveSnapshot({
                profile,
                run: mode === 'demo' ? (sourceFor(mode, scope, preference)?.run ?? source.run) : source.run,
                previous: previous?.profile?.kind === profile.kind ? previous : EMPTY_LIVE_SNAPSHOT,
                countUsersOnline:
                    preference !== 'all' || !(source.statsHost !== null && info?.token && statsActive.current),
                pathCleaning: info?.pathCleaning ?? false,
                now: Date.now(),
                signal,
            })
            completedPreference.current = preference
            return { ...result, data: { ...result.data, preference } }
        },
        [source, mode, scope, preference]
    )
    const onEvent = useCallback((event: LiveControllerEvent) => {
        if (event === 'background_stopped') {
            trackLivePaused({ trigger: 'background' })
        } else {
            trackLiveResumed({ trigger: 'foreground' })
        }
    }, [])
    const main = usePoller<LiveSnapshot>({
        enabled: source !== null && project.info !== undefined && !notSetUp,
        read,
        intervalMs: READ_INTERVAL_MS,
        slowdown: READ_SLOWDOWN,
        onEvent,
    })
    const slowEnabled = source !== null && project.info !== undefined && !notSetUp && preference !== 'web'
    const slow = useMobileMetrics(source, slowEnabled)
    const preferredKind = preference === 'all' ? 'mixed' : preference
    const mismatch = main.state.data !== null && main.state.data.preference !== preference
    const fastSnapshot = mismatch
        ? {
              ...EMPTY_LIVE_SNAPSHOT,
              profile: {
                  kind: preferredKind as 'web' | 'mobile' | 'mixed' | 'unknown',
              },
          }
        : (main.state.data ?? EMPTY_LIVE_SNAPSHOT)
    const snapshot =
        slowEnabled && slow.state.data
            ? {
                  ...fastSnapshot,
                  mobileMetrics: { ...slow.state.data, sessions: fastSnapshot.mobileMetrics?.sessions ?? null },
              }
            : fastSnapshot
    const lastPreference = useRef(preference)
    const audienceRead = useRef({ preference, paused: main.state.paused, active: main.screenActive })
    audienceRead.current = { preference, paused: main.state.paused, active: main.screenActive }
    useEffect(() => {
        if (lastPreference.current !== preference && !main.state.paused && main.screenActive && main.controller) {
            lastPreference.current = preference
            const controller = main.controller
            void controller.refresh().then(() => {
                const latest = audienceRead.current
                if (
                    latest.preference === preference &&
                    !latest.paused &&
                    latest.active &&
                    completedPreference.current !== preference
                ) {
                    void controller.refresh()
                }
            })
        }
    }, [preference, main.controller, main.state.paused, main.screenActive])
    const state = source && project.info !== undefined ? liveProjectState(snapshot, project.info) : null
    useLiveStateShown(state)
    // Quiet shows no users online, and the 30-second read ends Quiet, so the stats read waits until then.
    const stats = useStatsUsersOnline(
        source,
        STATS_INTERVAL_MS,
        project.info,
        !notSetUp && state !== 'quiet',
        preference === 'all'
    )
    statsActive.current = stats.active

    const paused = main.state.paused
    useEffect(() => {
        if (paused) {
            stats.controller?.pause()
            slow.controller?.pause()
        } else {
            void stats.controller?.resume()
            void slow.controller?.resume()
        }
    }, [paused, stats.controller, slow.controller])

    // Keep one message per failure streak, including when polling pauses and resumes.
    const mainFailing = main.state.failures > 0
    const slowFailing = slowEnabled && slow.state.failures > 0
    const failing = mainFailing || slowFailing
    const hasData = main.state.data !== null && !mismatch
    const reconnecting = useDelayedReconnecting(
        failing && !paused && main.screenActive,
        source,
        async (): Promise<void> => {
            await Promise.all([
                mainFailing ? main.controller?.checkRecovery() : undefined,
                slowFailing ? slow.controller?.checkRecovery() : undefined,
            ])
        }
    )
    const errorKind: LiveErrorKind | null =
        !hasData && mainFailing ? 'load_failed' : reconnecting ? 'refresh_failed' : null
    const onErrorRef = useRef(onError)
    onErrorRef.current = onError
    const shownError = useRef<{ source: LiveSource | null; kind: LiveErrorKind } | null>(null)
    useEffect(() => {
        if (!failing) {
            shownError.current = null
        } else if (errorKind && (shownError.current?.source !== source || shownError.current.kind !== errorKind)) {
            shownError.current = { source, kind: errorKind }
            trackLiveErrorShown({ kind: errorKind })
            onErrorRef.current(errorKind)
        }
    }, [errorKind, failing, source])

    const { recheck } = project
    const unknownProject = project.info === null
    const screenActive = main.screenActive
    useEffect(() => {
        if (!screenActive || !(notSetUp || unknownProject)) {
            return undefined
        }
        void recheck(PROJECT_RECHECK_MS)
        const timer = setInterval(() => void recheck(PROJECT_RECHECK_MS), PROJECT_RECHECK_MS)
        return () => clearInterval(timer)
    }, [notSetUp, unknownProject, screenActive, recheck])

    const [pulling, setPulling] = useState(false)
    const pull = useCallback(() => {
        trackLiveRefreshed({ trigger: 'pull' })
        setPulling(true)
        // A pull is a person asking, so it reads the project now instead of waiting out the minute.
        const reads = notSetUp ? [recheck(0)] : [main.controller?.refresh(), stats.controller?.refresh()]
        if (!notSetUp) void slow.controller?.refresh()
        void Promise.all(reads).finally(() => setPulling(false))
    }, [notSetUp, recheck, main.controller, stats.controller, slow.controller])
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
        void slow.controller?.refresh()
    }, [main.controller, slow.controller])

    let status: LiveStatus = source ? liveStatus(main.state) : 'loading'
    if (status === 'reconnecting' && !reconnecting) status = hasData ? 'live' : 'loading'
    if (reconnecting && !paused) status = 'reconnecting'
    return {
        screenActive,
        snapshot,
        state,
        status,
        updatedAt: main.state.updatedAt,
        usersOnline: stats.count ?? snapshot.usersOnline,
        paused,
        reading: main.state.reading,
        loadFailed: mainFailing && !hasData,
        pulling,
        pull,
        pause,
        resume,
        retry,
    }
}

export interface LiveWorldFeed {
    world: LiveWorld | null
    status: LiveStatus
    screenActive: boolean
    loadFailed: boolean
    reading: boolean
    retry: () => void
}

/**
 * The countries screen's data. It starts from the countries Live's map card shared and reads the `geo` job alone on
 * Live's cadence, while Live's own read is stopped because Live lost focus. It reads nothing while Live is paused.
 * Mount it keyed by the session and project identity, like `useLiveFeed`.
 */
export function useLiveWorld(): LiveWorldFeed {
    const { preference } = useLivePreference()
    const mode = useDataMode()
    const scope = useProjectScope()
    const source = useMemo(() => sourceFor(mode, scope, preference), [mode, scope, preference])
    const shared = useLiveWorldShare()
    const read = useCallback(
        async (signal: AbortSignal): Promise<LiveReadResult<LiveWorld>> => {
            if (!source) {
                throw new Error('Live has no data source yet.')
            }
            return readLiveWorld({
                run: source.run,
                now: Date.now(),
                signal,
                mobileOnly: shared.mobileOnly,
                webOnly: shared.webOnly,
            })
        },
        [source, shared.mobileOnly, shared.webOnly]
    )
    const poller = usePoller<LiveWorld>({
        enabled: source !== null && !shared.paused,
        read,
        intervalMs: READ_INTERVAL_MS,
        slowdown: READ_SLOWDOWN,
    })
    const world = poller.state.data ?? shared.world
    const { controller } = poller
    const retry = useCallback((): void => {
        void controller?.refresh()
    }, [controller])
    return {
        world,
        status: liveStatus({ ...poller.state, data: world, paused: shared.paused }),
        screenActive: poller.screenActive,
        loadFailed: poller.state.failures > 0 && world === null,
        reading: poller.state.reading,
        retry,
    }
}
