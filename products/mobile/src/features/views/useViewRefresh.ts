import { focusManager } from '@tanstack/react-query'
import { useFocusEffect, useIsFocused } from 'expo-router'
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'

import type { BudgetFamily } from '@/api/budget'
import { serverNow } from '@/api/serverClock'
import { addSessionEndTask } from '@/auth/authStore'
import { sleep } from '@/lib/sleep'
import { useNow } from '@/lib/useNow'
import type { Freshness } from '@/model/views'

import { type RefreshTrigger, trackViewsRefreshed, type ViewsScreen } from './analytics'
import {
    type BlockedState,
    blockedState,
    cacheTargetPassed,
    dashboardFloorUntil,
    hasGoodValue,
    isDue,
    isEligible,
    RECHECK_MS,
    REFRESH_MIN_MS,
    readFloorPassed,
    type StatusLine,
    statusLine,
} from './freshness'
import { type JobResult, type ReadResult, type RefreshMode, viewsQueue } from './refreshQueue'
import { useItemErrors } from './viewsCache'

addSessionEndTask(() => {
    viewsQueue.reset()
})

/** One data item on a screen: a Number or Chart pin, a dashboard tile, the insight, or the web analytics overview. */
export interface RefreshItem {
    /** The freshness key. Items with one key share one cache entry and one request. */
    key: string
    family: BudgetFamily
    /** Reads the cached snapshot when called, so a pass sees what an earlier step of the same pass wrote. */
    snapshot: () => Freshness | undefined
    /** Sends one read and writes the result to the cache, also on failure (`readAt`, `refreshFailed`). */
    read: (mode: RefreshMode, signal: AbortSignal) => Promise<ReadResult>
    /**
     * A pull's read for an item still inside its window: `force_cache` for insights, `blocking` for `POST query/`,
     * which has no cache-only read and returns its cache inside the window.
     */
    windowMode: 'force_cache' | 'blocking'
    /**
     * False for an insight whose kind the phone cannot draw. It shows the web card whatever its result, so no pass
     * computes it. Before the first read the kind is unknown, so it is drawable. Missing means drawable.
     */
    drawable?: () => boolean
    /** Pinned dashboard cache reads seed snapshots before a tile's first compute, so those items can be due at once. */
    openDue?: () => boolean
}

/** The dashboard read that carries every tile. A dashboard read counts as a read of each tile it carries. */
export interface RefreshContainer {
    /** Changes with the range override, which starts a new open path. */
    key: string
    family: BudgetFamily
    readAt: () => number | null
    /** `GET dashboards/{id}/?refresh=force_cache`. */
    read: (signal: AbortSignal) => Promise<ReadResult>
    /** `Dashboard.last_refresh`, for the web's shared bulk floor. */
    lastRefresh: () => string | null
}

/** A list read that pull and focus also refresh: the pin list and the web-viewed dashboards in Recent. */
export interface RefreshList {
    key: string
    /** Device ms of the last successful read, 0 when never read. */
    updatedAt: () => number
    refetch: () => Promise<unknown>
}

export interface ViewRefreshOptions {
    screen: ViewsScreen
    dataScope: string
    screenKey: string
    /** Every data item, in screen order (top first). */
    items: readonly RefreshItem[]
    /** The keys on screen now. Undefined until the list reports them: the first `INITIAL_VISIBLE_ROWS` items count. */
    visibleKeys?: ReadonlySet<string>
    container?: RefreshContainer | null
    lists?: readonly RefreshList[]
    /** False while signed out, loading, or without the Views scopes: no pass runs. */
    enabled: boolean
    /** Changes when the user picks another range, so the next first read reports `range`. */
    rangeKey?: string
}

export interface ViewRefresh {
    status: StatusLine
    /** A read of the screen runs, or a pull's feedback still shows. */
    busy: boolean
    hint: string | null
    blocked: BlockedState
    pulling: boolean
    onPull: () => void
    refreshItem: (key: string) => boolean
    /**
     * "Try again" on a screen with nothing to show: the dashboard read, or `blocking` for each item without a value. It
     * goes out even inside the minute floor, and it never forces.
     */
    retry: () => void
}

type PassTrigger = RefreshTrigger | 'open'

interface PassCounters {
    jobs: Promise<JobResult>[]
}

/** A list renders this many rows first (`initialNumToRender`). */
export const INITIAL_VISIBLE_ROWS = 6

function useQueueBusy(group: string): boolean {
    const subscribe = useCallback((listener: () => void) => viewsQueue.subscribe(listener), [])
    return useSyncExternalStore(subscribe, () => viewsQueue.isBusy(group))
}

// A list reports what it shows only after its rows lay out, which is after the first paint. Until then the rows it
// renders first count as visible, so a long dashboard does not compute every stale tile on open.
function visibleOf(options: ViewRefreshOptions): RefreshItem[] {
    const { items, visibleKeys } = options
    return visibleKeys ? items.filter((item) => visibleKeys.has(item.key)) : items.slice(0, INITIAL_VISIBLE_ROWS)
}

function drawable(item: RefreshItem): boolean {
    return item.drawable?.() !== false
}

/** The queue group: one per screen and range, so the reads of a range the user left can be dropped. */
function groupOf(options: Pick<ViewRefreshOptions, 'dataScope' | 'screenKey' | 'rangeKey'>): string {
    const screen = `${options.dataScope}|${options.screenKey}`
    return options.rangeKey === undefined ? screen : `${screen}|${options.rangeKey}`
}

function maxAgeSeconds(snapshots: readonly (Freshness | undefined)[], now: number): number | null {
    const times = snapshots.flatMap((snapshot) => (snapshot?.lastRefreshAt ? [Date.parse(snapshot.lastRefreshAt)] : []))
    return times.length > 0 ? Math.round((now - Math.min(...times)) / 1000) : null
}

function blockedFor(options: ViewRefreshOptions, now: number = serverNow()): BlockedState {
    const snapshots = visibleOf(options).map((item) => item.snapshot())
    return blockedState({
        snapshots,
        dashboardFloorUntil: options.container
            ? dashboardFloorUntil(options.container.lastRefresh(), snapshots, now)
            : null,
        now,
    })
}

/**
 * Runs the refresh rules of one Views screen. It reads on first paint and when items scroll into view, on screen focus
 * and on app foreground (never forcing), and on pull to refresh (forcing only what the server allows). Every
 * request goes through the app-wide queue. No timer sends requests while the app is open.
 */
export function useViewRefresh(options: ViewRefreshOptions): ViewRefresh {
    const optionsRef = useRef(options)
    optionsRef.current = options
    const { enabled } = options
    const group = groupOf(options)
    const isFocused = useIsFocused()
    const isFocusedRef = useRef(isFocused)
    isFocusedRef.current = isFocused
    const passGeneration = useRef(0)
    const lastGroup = useRef(group)
    const lastEnabled = useRef(enabled)
    if (lastGroup.current !== group || lastEnabled.current !== enabled) {
        lastGroup.current = group
        lastEnabled.current = enabled
        passGeneration.current += 1
    }

    const stillActive = useCallback((generation: number, passGroup: string): boolean => {
        return (
            passGeneration.current === generation &&
            isFocusedRef.current &&
            optionsRef.current.enabled &&
            groupOf(optionsRef.current) === passGroup
        )
    }, [])

    const queueBusy = useQueueBusy(group)
    const [pulling, setPulling] = useState(false)
    const refreshInFlight = useRef(false)
    const busy = queueBusy || pulling
    const pendingRangeTrigger = useRef(false)
    const lastRangeKey = useRef(options.rangeKey)
    if (lastRangeKey.current !== options.rangeKey) {
        lastRangeKey.current = options.rangeKey
        pendingRangeTrigger.current = true
    }
    useNow(30_000)

    const containerReading = useRef<Promise<JobResult> | null>(null)

    const recordEmptyFailure = useCallback((key: string, result: JobResult, hasValue: () => boolean): void => {
        if ((result.status === 'failed' || result.status === 'capped') && !hasValue()) {
            const errors = useItemErrors.getState()
            if (!errors.errors[key]) {
                errors.set(key, 'failed')
            }
        }
    }, [])

    const send = useCallback(
        (
            counters: PassCounters,
            key: string,
            family: BudgetFamily,
            mode: RefreshMode,
            read: RefreshItem['read'],
            userRetry = false
        ) => {
            const job = viewsQueue.enqueue({
                key,
                family,
                group: groupOf(optionsRef.current),
                mode,
                run: read,
                userRetry,
            })
            counters.jobs.push(job)
            void job.then((result) =>
                recordEmptyFailure(key, result, () => {
                    const item = optionsRef.current.items.find((candidate) => candidate.key === key)
                    return !item || hasGoodValue(item.snapshot())
                })
            )
        },
        [recordEmptyFailure]
    )

    const readContainer = useCallback(
        (counters: PassCounters, container: RefreshContainer, userRetry = false): Promise<JobResult> => {
            const job = viewsQueue.enqueue({
                key: container.key,
                family: container.family,
                group: groupOf(optionsRef.current),
                mode: 'force_cache',
                run: (_mode, signal) => container.read(signal),
                userRetry,
            })
            counters.jobs.push(job)
            void job.then((result) => recordEmptyFailure(container.key, result, () => container.readAt() !== null))
            containerReading.current = job
            return job
        },
        [recordEmptyFailure]
    )

    const report = useCallback(
        async (
            trigger: PassTrigger,
            counters: PassCounters,
            startedAt: number,
            ageAtStart: number | null,
            blocked: BlockedState | null
        ): Promise<void> => {
            const results = await Promise.all(counters.jobs)
            const sent = results.filter((result) => ['ok', 'failed'].includes(result.status))
            const capped = results.find((result) => result.status === 'capped')
            const reported: RefreshTrigger | null = trigger === 'open' ? null : trigger
            if (!reported) {
                return
            }
            const quiet = (reported === 'focus' || reported === 'foreground') && sent.length === 0 && !capped
            if (quiet) {
                return
            }
            trackViewsRefreshed({
                trigger: reported,
                screen: optionsRef.current.screen,
                itemsRequested: sent.length,
                itemsForced: sent.filter((result) => result.forced).length,
                itemsComputed: sent.filter((result) => result.computed).length,
                itemsFailed: sent.filter((result) => result.status === 'failed').length,
                durationMs: Date.now() - startedAt,
                maxAgeSeconds: ageAtStart,
                blockedUntil:
                    blocked?.blocked && blocked.until !== null
                        ? Math.max(0, Math.round((blocked.until - serverNow()) / 1000))
                        : null,
                blockedReason: blocked?.blocked ? blocked.reason : null,
                cappedFamily: capped?.family ?? null,
            })
        },
        []
    )

    const refetchLists = useCallback(async (minAgeMs: number): Promise<void> => {
        await Promise.allSettled(
            (optionsRef.current.lists ?? [])
                .filter((list) => Date.now() - list.updatedAt() >= minAgeMs)
                .map(async (list) => list.refetch())
        )
    }, [])

    /** Open path for items seen for the first time: on mount, when they scroll into view, or after a range change. */
    const openItems = useCallback(
        async (
            fresh: RefreshItem[],
            trigger: PassTrigger,
            counters: PassCounters,
            generation: number,
            passGroup: string
        ) => {
            const current = optionsRef.current
            const startedAt = Date.now()
            const age = maxAgeSeconds(
                fresh.map((item) => item.snapshot()),
                serverNow()
            )
            if (current.container && containerReading.current) {
                await containerReading.current
            }
            if (!stillActive(generation, passGroup)) {
                return
            }
            for (const item of fresh) {
                const snapshot = item.snapshot()
                // Dashboard tiles follow the web's open path: after the cache-only dashboard read, a tile computes
                // only when it has no result or its `cache_target_age` has passed.
                const wanted = current.container
                    ? drawable(item) && (!hasGoodValue(snapshot) || cacheTargetPassed(snapshot))
                    : drawable(item) && (item.openDue?.() ?? isDue(snapshot))
                if (wanted) {
                    send(counters, item.key, item.family, 'blocking', item.read)
                }
            }
            await report(trigger, counters, startedAt, age, null)
        },
        [report, send, stillActive]
    )

    const focusPass = useCallback(
        async (trigger: 'focus' | 'foreground') => {
            const current = optionsRef.current
            const generation = passGeneration.current
            const passGroup = groupOf(current)
            if (!stillActive(generation, passGroup)) {
                return
            }
            const counters: PassCounters = { jobs: [] }
            const startedAt = Date.now()
            const visible = visibleOf(current)
            const age = maxAgeSeconds(
                visible.map((item) => item.snapshot()),
                serverNow()
            )
            void refetchLists(RECHECK_MS)
            if (current.container) {
                const readAt = current.container.readAt()
                if (!readAt || Date.now() - readAt >= RECHECK_MS) {
                    await readContainer(counters, current.container)
                }
                if (!stillActive(generation, passGroup)) {
                    return
                }
                for (const item of visibleOf(optionsRef.current)) {
                    const snapshot = item.snapshot()
                    if (drawable(item) && (!hasGoodValue(snapshot) || cacheTargetPassed(snapshot))) {
                        send(counters, item.key, item.family, 'blocking', item.read)
                    }
                }
            } else {
                for (const item of visible) {
                    if (drawable(item) && (item.openDue?.() ?? isDue(item.snapshot()))) {
                        send(counters, item.key, item.family, 'blocking', item.read)
                    }
                }
            }
            await report(trigger, counters, startedAt, age, null)
        },
        [readContainer, refetchLists, report, send, stillActive]
    )

    const pullPass = useCallback(async () => {
        const current = optionsRef.current
        if (!current.enabled || !isFocusedRef.current) {
            return
        }
        const counters: PassCounters = { jobs: [] }
        const startedAt = Date.now()
        const generation = passGeneration.current
        const passGroup = groupOf(current)
        const age = maxAgeSeconds(
            visibleOf(current).map((item) => item.snapshot()),
            serverNow()
        )
        const listReads = refetchLists(0)
        if (current.container) {
            await readContainer(counters, current.container, true)
        }
        if (!stillActive(generation, passGroup)) {
            await Promise.all([listReads, report('pull', counters, startedAt, age, null)])
            return
        }
        const latest = optionsRef.current
        const now = serverNow()
        const blocked = blockedFor(latest, now)
        for (const item of visibleOf(latest)) {
            const snapshot = item.snapshot()
            if (drawable(item) && !blocked.blocked && isEligible(snapshot, now)) {
                send(counters, item.key, item.family, 'force_blocking', item.read, true)
            } else if (drawable(item) && !hasGoodValue(snapshot)) {
                send(counters, item.key, item.family, 'blocking', item.read, true)
            } else if (!latest.container) {
                send(counters, item.key, item.family, item.windowMode, item.read, true)
            }
        }
        await Promise.all([listReads, report('pull', counters, startedAt, age, blocked)])
    }, [readContainer, refetchLists, report, send, stillActive])

    // First paint and items that come into view. A container (dashboard) read goes first when its key is new.
    const seen = useRef(new Set<string>())
    const seenGroup = useRef(group)
    const containerKey = useRef<string | null>(null)
    const itemKeys = options.items.map((item) => item.key).join('|')
    const visibleKeyList = options.visibleKeys ? [...options.visibleKeys].sort().join('|') : '*'
    // biome-ignore lint/correctness/useExhaustiveDependencies: the key strings stand for the items, read through the ref.
    useEffect(() => {
        if (!enabled || !isFocused) {
            return
        }
        const current = optionsRef.current
        const counters: PassCounters = { jobs: [] }
        if (seenGroup.current !== groupOf(current)) {
            // Leaving a range dropped its queued reads, so coming back to it checks its items again.
            seenGroup.current = groupOf(current)
            seen.current.clear()
        }
        let containerOpened = false
        if (current.container && containerKey.current !== current.container.key) {
            containerKey.current = current.container.key
            containerOpened = true
            if (readFloorPassed(current.container.readAt())) {
                void readContainer(counters, current.container)
            } else {
                containerReading.current = null
            }
        }
        const fresh = visibleOf(current).filter((item) => !seen.current.has(item.key))
        for (const item of fresh) {
            seen.current.add(item.key)
        }
        if (!containerOpened && fresh.length === 0) {
            return
        }
        const trigger: PassTrigger = pendingRangeTrigger.current ? 'range' : 'open'
        pendingRangeTrigger.current = false
        void openItems(fresh, trigger, counters, passGeneration.current, group)
    }, [enabled, isFocused, group, itemKeys, visibleKeyList, options.container?.key, openItems, readContainer])

    // Screen focus after the first one, which is the mount. Leaving drops what only this screen queued.
    const focusedBefore = useRef(false)
    useFocusEffect(
        useCallback(() => {
            if (focusedBefore.current) {
                void focusPass('focus')
            }
            focusedBefore.current = true
            return () => {
                passGeneration.current += 1
                viewsQueue.leave(groupOf(optionsRef.current))
            }
        }, [focusPass])
    )

    // App foreground after a minute or more in the background, while this screen is the focused one.
    useEffect(() => {
        let backgroundAt: number | null = null
        return focusManager.subscribe((focused) => {
            if (!focused) {
                backgroundAt = Date.now()
                return
            }
            if (backgroundAt !== null && Date.now() - backgroundAt >= 60_000 && isFocusedRef.current) {
                void focusPass('foreground')
            }
            backgroundAt = null
        })
    }, [focusPass])

    // A new range, and unmount, drop the queued reads of the range on screen until now. The current range goes first.
    useEffect(() => () => viewsQueue.leave(group), [group])

    const blocked = enabled ? blockedFor(options) : blockedState({ snapshots: [] })

    const onPull = useCallback((): void => {
        if (!optionsRef.current.enabled || refreshInFlight.current) {
            return
        }
        refreshInFlight.current = true
        setPulling(true)
        void Promise.allSettled([pullPass(), sleep(REFRESH_MIN_MS)]).then(() => {
            refreshInFlight.current = false
            setPulling(false)
        })
    }, [pullPass])

    const refreshItem = useCallback(
        (key: string): boolean => {
            const current = optionsRef.current
            const item = current.items.find((candidate) => candidate.key === key)
            if (!item || !current.enabled) {
                return false
            }
            const snapshot = item.snapshot()
            const mode: RefreshMode =
                drawable(item) && !blockedFor(current).blocked && isEligible(snapshot)
                    ? 'force_blocking'
                    : drawable(item) && !hasGoodValue(snapshot)
                      ? 'blocking'
                      : item.windowMode
            const job = viewsQueue.enqueue({
                key: item.key,
                family: item.family,
                group: groupOf(current),
                mode,
                run: item.read,
                userRetry: true,
            })
            void job.then((result) => recordEmptyFailure(item.key, result, () => hasGoodValue(item.snapshot())))
            return true
        },
        [recordEmptyFailure]
    )

    const retry = useCallback(() => {
        const current = optionsRef.current
        if (!current.enabled) {
            return
        }
        const counters: PassCounters = { jobs: [] }
        if (current.container) {
            // When the dashboard arrives, its tiles are new items, so the open path reads them.
            void readContainer(counters, current.container, true)
            return
        }
        for (const item of visibleOf(current)) {
            if (drawable(item) && !hasGoodValue(item.snapshot())) {
                send(counters, item.key, item.family, 'blocking', item.read, true)
            }
        }
    }, [readContainer, send])

    const status = statusLine(
        visibleOf(options).map((item) => item.snapshot()),
        busy
    )

    return {
        status: enabled ? status : { kind: 'hidden', text: null },
        busy,
        hint: null,
        blocked,
        pulling,
        onPull,
        refreshItem,
        retry,
    }
}

export type { ReadResult, RefreshMode } from './refreshQueue'
