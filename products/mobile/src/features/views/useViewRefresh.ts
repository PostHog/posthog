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
    bulkFloorUntil,
    cacheReadAllowed,
    cacheTargetPassed,
    clearBulkFloors,
    dashboardFloorUntil,
    HINT_MS,
    hasGoodValue,
    isDue,
    isEligible,
    RECHECK_MS,
    REFRESH_MIN_MS,
    readFloorPassed,
    refreshHintText,
    type StatusLine,
    startBulkFloor,
    statusLine,
} from './freshness'
import { type JobResult, type ReadResult, type RefreshMode, viewsQueue } from './refreshQueue'
import { useItemErrors } from './viewsCache'

addSessionEndTask(() => {
    viewsQueue.reset()
    clearBulkFloors()
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
     * The button's read for an item still inside its window: `force_cache` for insights, `blocking` for `POST query/`,
     * which has no cache-only read and returns its cache inside the window.
     */
    windowMode: 'force_cache' | 'blocking'
    /**
     * False for an insight whose kind the phone cannot draw. It shows the web card whatever its result, so no pass
     * computes it. Before the first read the kind is unknown, so it is drawable. Missing means drawable.
     */
    drawable?: () => boolean
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

/** A list read the button and focus also refresh: the pin list and the web-viewed dashboards in Recent. */
export interface RefreshList {
    key: string
    /** Device ms of the last successful read, 0 when never read. */
    updatedAt: () => number
    refetch: () => Promise<unknown>
}

export interface ViewRefreshOptions {
    screen: ViewsScreen
    /** `demo` or the project (`useViewsContext().dataScope`): floors and queue groups never cross from one to another. */
    dataScope: string
    /** The bulk floor key, and the queue group with `rangeKey`: `list`, `dashboard:{id}`, `insight:{short_id}`, `web`. */
    screenKey: string
    /** Every data item, in screen order (top first). */
    items: readonly RefreshItem[]
    /** The keys on screen now. Undefined until the list reports them: the first `INITIAL_VISIBLE_ROWS` items count. */
    visibleKeys?: ReadonlySet<string>
    container?: RefreshContainer | null
    lists?: readonly RefreshList[]
    /** The list and dashboards allow one button or pull pass per 5 minutes. */
    bulkFloor: boolean
    /** False while signed out, loading, or without the Views scopes: no pass runs. */
    enabled: boolean
    /** Changes when the user picks another range, so the next first read reports `range`. */
    rangeKey?: string
}

export type RefreshButtonState = 'idle' | 'busy' | 'blocked'

export interface ViewRefresh {
    status: StatusLine
    button: RefreshButtonState
    /** "You can refresh again in 3 min." for 3 s after a tap or pull that could not force. */
    hint: string | null
    blocked: BlockedState
    pulling: boolean
    onButton: () => void
    onPull: () => void
    /** A tile menu's "Refresh": forces the item when it is eligible, else shows the hint. True when it sent a request. */
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

/** The bulk floor key: one per screen in each data scope. */
function floorKeyOf(options: Pick<ViewRefreshOptions, 'dataScope' | 'screenKey'>): string {
    return `${options.dataScope}|${options.screenKey}`
}

/** The queue group: one per screen and range, so the reads of a range the user left can be dropped. */
function groupOf(options: Pick<ViewRefreshOptions, 'dataScope' | 'screenKey' | 'rangeKey'>): string {
    const screen = floorKeyOf(options)
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
        bulkFloorUntil: options.bulkFloor ? bulkFloorUntil(floorKeyOf(options)) : null,
        dashboardFloorUntil: options.container
            ? dashboardFloorUntil(options.container.lastRefresh(), snapshots, now)
            : null,
        now,
    })
}

/**
 * Runs the refresh rules of one Views screen. It reads on first paint and when items scroll into view, on screen focus
 * and on app foreground (never forcing), and on the button or pull (forcing only what the server allows). Every
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
    const [hintUntil, setHintUntil] = useState<{ text: string; until: number } | null>(null)
    const [manualRefresh, setManualRefresh] = useState<'button' | 'pull' | null>(null)
    const refreshInFlight = useRef(false)
    const busy = queueBusy || manualRefresh !== null
    const [, setTick] = useState(0)
    const pendingRangeTrigger = useRef(false)
    const lastRangeKey = useRef(options.rangeKey)
    if (lastRangeKey.current !== options.rangeKey) {
        lastRangeKey.current = options.rangeKey
        pendingRangeTrigger.current = true
    }
    // Relative ages and the blocked state move with time.
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

    const showHint = useCallback((until: number | null) => {
        setHintUntil({ text: refreshHintText(until), until: Date.now() + HINT_MS })
    }, [])

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
                    : drawable(item) && isDue(snapshot)
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
                    if (drawable(item) && isDue(item.snapshot())) {
                        send(counters, item.key, item.family, 'blocking', item.read)
                    }
                }
            }
            await report(trigger, counters, startedAt, age, null)
        },
        [readContainer, refetchLists, report, send, stillActive]
    )

    const cacheOnlyReads = useCallback(
        (counters: PassCounters) => {
            const current = optionsRef.current
            if (current.container) {
                if (readFloorPassed(current.container.readAt())) {
                    void readContainer(counters, current.container)
                }
                return
            }
            for (const item of visibleOf(current)) {
                if (cacheReadAllowed(item.snapshot()?.readAt, current.bulkFloor)) {
                    send(counters, item.key, item.family, item.windowMode, item.read)
                }
            }
        },
        [readContainer, send]
    )

    const tapPass = useCallback(
        async (trigger: 'button' | 'pull') => {
            const current = optionsRef.current
            if (!current.enabled) {
                return
            }
            const counters: PassCounters = { jobs: [] }
            const startedAt = Date.now()
            const now = serverNow()
            const visible = visibleOf(current)
            const age = maxAgeSeconds(
                visible.map((item) => item.snapshot()),
                now
            )
            const blocked = blockedFor(current, now)
            if (blocked.blocked) {
                showHint(blocked.until)
                const listReads = trigger === 'pull' ? refetchLists(60_000) : Promise.resolve()
                if (trigger === 'pull') {
                    cacheOnlyReads(counters)
                }
                await Promise.all([listReads, report(trigger, counters, startedAt, age, blocked)])
                return
            }
            const listReads = refetchLists(60_000)
            let forced = false
            let rest = false
            for (const item of visible) {
                const snapshot = item.snapshot()
                if (!drawable(item)) {
                    if (current.container) {
                        rest = true
                    } else if (cacheReadAllowed(snapshot?.readAt, current.bulkFloor)) {
                        send(counters, item.key, item.family, item.windowMode, item.read)
                    }
                } else if (isEligible(snapshot, now)) {
                    forced = true
                    send(counters, item.key, item.family, 'force_blocking', item.read)
                } else if (!hasGoodValue(snapshot)) {
                    send(counters, item.key, item.family, 'blocking', item.read)
                } else if (current.container) {
                    rest = true
                } else if (cacheReadAllowed(snapshot?.readAt, current.bulkFloor)) {
                    send(counters, item.key, item.family, item.windowMode, item.read)
                }
            }
            // A dashboard that never loaded has no tiles to read, so the button reads the dashboard itself.
            const neverLoaded = current.container?.readAt() === null
            if (current.container && (rest || neverLoaded) && readFloorPassed(current.container.readAt())) {
                void readContainer(counters, current.container)
            }
            if (forced && current.bulkFloor) {
                startBulkFloor(floorKeyOf(current), now)
            }
            await Promise.all([listReads, report(trigger, counters, startedAt, age, null)])
        },
        [cacheOnlyReads, readContainer, refetchLists, report, send, showHint]
    )

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

    // The hint hides after 3 s.
    useEffect(() => {
        if (!hintUntil) {
            return
        }
        const timer = setTimeout(() => setHintUntil(null), Math.max(0, hintUntil.until - Date.now()))
        return () => clearTimeout(timer)
    }, [hintUntil])

    const blocked = enabled ? blockedFor(options) : blockedState({ snapshots: [], bulkFloorUntil: null })
    // Re-render when the blocked state ends, so the check turns back into the refresh icon on time.
    useEffect(() => {
        if (!blocked.blocked || blocked.until === null) {
            return
        }
        const timer = setTimeout(() => setTick((tick) => tick + 1), Math.max(0, blocked.until - serverNow()) + 50)
        return () => clearTimeout(timer)
    }, [blocked.blocked, blocked.until])

    const startManualRefresh = useCallback(
        (trigger: 'button' | 'pull'): void => {
            if (!optionsRef.current.enabled || refreshInFlight.current) {
                return
            }
            refreshInFlight.current = true
            setManualRefresh(trigger)
            void Promise.allSettled([tapPass(trigger), sleep(REFRESH_MIN_MS)]).then(() => {
                refreshInFlight.current = false
                setManualRefresh(null)
            })
        },
        [tapPass]
    )

    const onButton = useCallback(() => startManualRefresh('button'), [startManualRefresh])

    const onPull = useCallback(() => startManualRefresh('pull'), [startManualRefresh])

    const refreshItem = useCallback(
        (key: string): boolean => {
            const current = optionsRef.current
            const item = current.items.find((candidate) => candidate.key === key)
            if (!item || !current.enabled) {
                return false
            }
            const snapshot = item.snapshot()
            const mode: RefreshMode | null = isEligible(snapshot)
                ? 'force_blocking'
                : hasGoodValue(snapshot)
                  ? null
                  : 'blocking'
            if (!mode) {
                showHint(blockedState({ snapshots: [snapshot], bulkFloorUntil: null }).until)
                return false
            }
            const job = viewsQueue.enqueue({
                key: item.key,
                family: item.family,
                group: groupOf(current),
                mode,
                run: item.read,
                // A tap on an item without a value, such as Load on a tile, follows the open pass's read within the
                // minute floor. It never forces, so it goes out like "Try again".
                userRetry: mode === 'blocking',
            })
            void job.then((result) => recordEmptyFailure(item.key, result, () => hasGoodValue(item.snapshot())))
            return true
        },
        [recordEmptyFailure, showHint]
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
    const button: RefreshButtonState = busy ? 'busy' : blocked.blocked ? 'blocked' : 'idle'

    return {
        status: enabled ? status : { kind: 'hidden', text: null },
        button,
        hint: hintUntil?.text ?? null,
        blocked,
        pulling: manualRefresh === 'pull',
        onButton,
        onPull,
        refreshItem,
        retry,
    }
}

export type { ReadResult, RefreshMode } from './refreshQueue'
