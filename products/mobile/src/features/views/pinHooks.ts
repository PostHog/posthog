import { type QueryClient, type QueryKey, useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ViewToken } from 'react-native'
import { useShallow } from 'zustand/react/shallow'
import { fetchRecentDashboards } from '@/api/dashboards'
import type { PaginatedApi, ProjectScope } from '@/api/reports'
import {
    createShortcut,
    deleteShortcut,
    type FileSystemShortcutApi,
    fetchShortcuts,
    SHORTCUT_PAGE_SIZE,
} from '@/api/shortcuts'
import { useAuthStore } from '@/auth/authStore'
import { sessionGeneration } from '@/auth/tokens'
import { useDemoViews } from '@/demo/views'
import { abortError } from '@/lib/abort'
import { toError } from '@/lib/errors'
import { mergeRecent, pinsFromShortcuts, shortcutMatchKey } from '@/model/adapters/viewPins'
import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { QueryState } from '@/model/types'
import type {
    DashboardTileView,
    DeviceRecentEntry,
    InsightSnapshot,
    PinDisplay,
    PinDisplayMode,
    PinView,
    RecentView,
} from '@/model/views'

import {
    type PinSource,
    trackPinDisplayChanged,
    trackPinsReordered,
    trackPinTileChosen,
    trackViewPinned,
    trackViewUnpinned,
} from './analytics'
import { cacheTargetPassed, hasGoodValue, isDue, READ_FLOOR_MS } from './freshness'
import { type InsightTarget, insightItem, insightItemKey, insightQueryKey, pinTarget } from './items'
import { listRead, retryListRead } from './listReads'
import { movedOrder, usePinPrefs, useProjectPinPrefs } from './pinPrefsStore'
import { useDeviceRecent } from './recentStore'
import { viewsQueue } from './refreshQueue'
import { type PinTarget, pinTargetKey, shortcutInputFor } from './shortcutInput'
import { type PinDisplayPrefs, resolvePinDisplays } from './smartPinDisplay'
import { pinRangeLabel } from './snapshotChart'
import { useSmartPinDisplays } from './useSmartPinDisplays'
import { type RefreshList, useViewRefresh, type ViewRefresh } from './useViewRefresh'
import { reportScopeError } from './useViewsAccess'
import { useViewsContext } from './useViewsContext'
import { freshnessKey, type ItemErrorKind, useItemError, useItemUpdating, useSnapshot, viewsKeys } from './viewsCache'

type ShortcutPage = PaginatedApi<FileSystemShortcutApi>

const EMPTY_ROWS: FileSystemShortcutApi[] = []
const EMPTY_RECENT: DeviceRecentEntry[] = []

function readShortcuts(signal?: AbortSignal, beforeRead?: () => void): Promise<ShortcutPage> {
    return listRead('dashboards', signal, () => {
        beforeRead?.()
        return fetchShortcuts(signal)
    })
}

function projectKey(scope: ProjectScope): string {
    return `${scope.host}|${scope.projectId}`
}

/** The display modes a pin offers. Web analytics and pins that open on the web show as rows only. */
export function pinModes(pin: Pick<PinView, 'kind' | 'native'>): PinDisplayMode[] {
    return pin.native && (pin.kind === 'insight' || pin.kind === 'dashboard') ? ['row', 'number', 'chart'] : ['row']
}

export interface PinsState {
    pins: QueryState<PinView[]>
    displayPrefs: PinDisplayPrefs
    /** The server holds more pins than one page: show "Showing 100 pins". */
    truncated: boolean
    /** For the refresh rules: the last read of the pin list, and a re-read. */
    list: RefreshList
}

/**
 * The pins, in this phone's order: ranked pins first, new ones after them in server order. Rows for one view collapse
 * into one pin. A complete list read forgets the order and mode of pins that are gone.
 *
 * Only the Views list passes `refetchOnMount`. Pin buttons and error states on view screens read the cached list, so
 * opening a view sends no pin list request; the list's refresh rules own the re-reads.
 */
export function usePins({ refetchOnMount = false }: { refetchOnMount?: boolean } = {}): PinsState {
    const context = useViewsContext()
    const demo = context.mode === 'demo'
    const queryKey = viewsKeys.shortcuts(context.scope)
    const query = useQuery({
        queryKey,
        queryFn: ({ signal }) => readShortcuts(signal),
        enabled: context.ready && !demo,
        staleTime: READ_FLOOR_MS,
        refetchOnMount,
        retry: retryListRead,
    })
    const prefsKey = context.scope ? projectKey(context.scope) : null
    const livePrefs = useProjectPinPrefs(prefsKey)
    const demoState = useDemoViews(
        useShallow((state) => ({ rows: state.shortcuts, rank: state.rank, display: state.display }))
    )
    const rows = demo ? demoState.rows : (query.data?.results ?? EMPTY_ROWS)
    const prefs = demo ? demoState : livePrefs
    const pins = useMemo(() => pinsFromShortcuts(rows, prefs), [rows, prefs])

    const page = query.data
    useEffect(() => {
        if (!page || demo || !prefsKey) {
            return
        }
        const complete = !page.next && page.results.length < SHORTCUT_PAGE_SIZE
        usePinPrefs.getState().prune(
            prefsKey,
            page.results.map((row) => row.id),
            complete
        )
    }, [page, demo, prefsKey])

    const { refetch, dataUpdatedAt } = query
    const list = useMemo<RefreshList>(
        () => ({
            key: 'pins',
            updatedAt: () => (demo ? Date.now() : dataUpdatedAt),
            refetch: () => (demo ? Promise.resolve() : refetch()),
        }),
        [demo, dataUpdatedAt, refetch]
    )

    let state: QueryState<PinView[]>
    if (context.mode === 'loading' || (!context.ready && context.access.state === 'ok')) {
        state = loadingQuery()
    } else if (demo || query.data) {
        state = successQuery(pins, { isRefetching: query.isRefetching, refetch })
    } else if (query.isError) {
        state = errorQuery(toError(query.error), refetch)
    } else {
        state = { ...loadingQuery<PinView[]>(), refetch }
    }
    return {
        pins: state,
        displayPrefs: prefs.display,
        truncated: Boolean(page && (page.next || page.count > SHORTCUT_PAGE_SIZE)),
        list,
    }
}

/** Match keys of every pinned view, for a pin button's state. */
export function usePinnedKeys(): ReadonlySet<string> {
    const { pins } = usePins()
    const data = pins.data
    return useMemo(() => new Set((data ?? []).map((pin) => shortcutMatchKey(pin.type, pin.ref))), [data])
}

export interface PinActions {
    isPinned: (target: PinTarget) => boolean
    /** Shows the pin at once and rolls back on failure. Rejects with user-facing copy for a toast. */
    pin: (target: PinTarget, from: PinSource) => Promise<void>
    /** Deletes every row that matches the view, in every environment. Rejects with user-facing copy. */
    unpin: (view: PinView | PinTarget, from: PinSource) => Promise<void>
    /**
     * `needs_tile`: a dashboard pin needs a tile before Number or Chart, so open "Choose tile" with the first eligible
     * tile selected and call `chooseTile`.
     */
    setDisplayMode: (pin: PinView, mode: PinDisplayMode) => 'done' | 'needs_tile'
    chooseTile: (pin: PinView, mode: 'number' | 'chart', tile: DashboardTileView) => void
    /** "Move up" (-1) and "Move down" (1), on this phone only. */
    move: (pin: PinView, direction: -1 | 1) => void
    /** "Edit pins" drag: the new order of shortcut ids, on this phone only. */
    reorder: (shortcutIds: readonly string[]) => void
    pending: boolean
}

function rowsFor(page: ShortcutPage | undefined): FileSystemShortcutApi[] {
    return page?.results ?? []
}

function withRows(page: ShortcutPage | undefined, rows: FileSystemShortcutApi[]): ShortcutPage {
    return { count: rows.length, next: page?.next ?? null, results: rows }
}

/** The pin list a pin or unpin changes: the project's cached shortcut page, or the demo store. */
export interface PinWriteTarget {
    client: QueryClient
    listKey: QueryKey
    demo: boolean
    isCurrent: () => boolean
}

function assertCurrentWrite(list: PinWriteTarget): void {
    if (!list.isCurrent()) {
        throw abortError()
    }
}

// Pin and unpin of one view run one after another, from every screen, so a second tap waits for the first instead of
// being dropped. An unpin that waits for a pin then finds the row the pin created and deletes it.
const pinWrites = new Map<string, Promise<void>>()

function queuePinWrite(list: PinWriteTarget, matchKey: string, run: () => Promise<void>): Promise<void> {
    const key = `${list.demo ? 'demo' : freshnessKey(list.listKey)}|${matchKey}`
    const next = (pinWrites.get(key) ?? Promise.resolve()).then(() => {
        assertCurrentWrite(list)
        return run()
    })
    const settled = next.catch(() => undefined)
    pinWrites.set(key, settled)
    void settled.then(() => {
        if (pinWrites.get(key) === settled) {
            pinWrites.delete(key)
        }
    })
    return next
}

/**
 * Pins a view: shows it at once and rolls back on failure. Resolves once the pin is saved, or at once when the view is
 * already pinned. Rejects with user-facing copy for a toast.
 */
export function pinView(list: PinWriteTarget, target: PinTarget, from: PinSource): Promise<void> {
    const key = pinTargetKey(target)
    return queuePinWrite(list, key, async () => {
        const input = shortcutInputFor(target)
        if (list.demo) {
            const shortcuts = useDemoViews.getState().shortcuts
            if (!shortcuts.some((row) => shortcutMatchKey(row.type, row.ref) === key)) {
                useDemoViews.getState().addShortcut(input)
                trackViewPinned({ viewType: target.kind, from })
            }
            return
        }
        const { client, listKey } = list
        // A pin list a minute old may miss a star made on the web since, which would make a second row.
        const state = client.getQueryState<ShortcutPage>(listKey)
        const page =
            state?.data && Date.now() - state.dataUpdatedAt < READ_FLOOR_MS
                ? state.data
                : await client.fetchQuery({
                      queryKey: listKey,
                      queryFn: async ({ signal }) => {
                          const page = await readShortcuts(signal, () => assertCurrentWrite(list))
                          assertCurrentWrite(list)
                          return page
                      },
                      staleTime: 0,
                  })
        assertCurrentWrite(list)
        if (rowsFor(page).some((row) => shortcutMatchKey(row.type, row.ref) === key)) {
            return
        }
        const pending: FileSystemShortcutApi = {
            ...input,
            id: `pending:${key}`,
            order: Math.max(0, ...rowsFor(page).map((row) => row.order ?? 0)) + 1,
            created_at: new Date().toISOString(),
        }
        client.setQueryData<ShortcutPage>(listKey, (current) => withRows(current, [...rowsFor(current), pending]))
        try {
            const created = await createShortcut(input)
            assertCurrentWrite(list)
            client.setQueryData<ShortcutPage>(listKey, (current) =>
                withRows(current, [
                    ...rowsFor(current).filter((row) => row.id !== pending.id && row.id !== created.id),
                    created,
                ])
            )
            trackViewPinned({ viewType: target.kind, from })
        } catch (error) {
            assertCurrentWrite(list)
            client.setQueryData<ShortcutPage>(listKey, (current) =>
                withRows(
                    current,
                    rowsFor(current).filter((row) => row.id !== pending.id)
                )
            )
            reportScopeError(error)
            viewsQueue.notePause('dashboards', error)
            throw new Error("Couldn't pin this view. Try again.")
        }
    })
}

/** Deletes every row that matches the view, in every environment. Rejects with user-facing copy for a toast. */
export function unpinView(list: PinWriteTarget, view: PinView | PinTarget, from: PinSource): Promise<void> {
    const key = 'shortcutId' in view ? shortcutMatchKey(view.type, view.ref) : pinTargetKey(view)
    return queuePinWrite(list, key, async () => {
        const viewType = view.kind
        const { client, listKey } = list
        const rows = list.demo ? useDemoViews.getState().shortcuts : rowsFor(client.getQueryData<ShortcutPage>(listKey))
        const ids = rows.filter((row) => shortcutMatchKey(row.type, row.ref) === key).map((row) => row.id)
        if (list.demo) {
            useDemoViews.getState().removeShortcuts(ids)
            trackViewUnpinned({ viewType, from, rowsDeleted: ids.length })
            return
        }
        client.setQueryData<ShortcutPage>(listKey, (current) =>
            withRows(
                current,
                rowsFor(current).filter((row) => !ids.includes(row.id))
            )
        )
        try {
            await Promise.all(ids.map((id) => deleteShortcut(id)))
            assertCurrentWrite(list)
            trackViewUnpinned({ viewType, from, rowsDeleted: ids.length })
        } catch (error) {
            assertCurrentWrite(list)
            reportScopeError(error)
            viewsQueue.notePause('dashboards', error)
            void client.invalidateQueries({ queryKey: listKey })
            throw new Error("Couldn't unpin this view. Try again.")
        }
    })
}

export function usePinActions(): PinActions {
    const context = useViewsContext()
    const demo = context.mode === 'demo'
    const { client, scope } = context.item
    const { pins, displayPrefs } = usePins()
    const pinnedKeys = usePinnedKeys()
    const listKey = viewsKeys.shortcuts(scope)
    const prefsKey = scope ? projectKey(scope) : null

    const setDisplay = useCallback(
        (shortcutId: string, display: PinDisplay) => {
            if (demo) {
                useDemoViews.getState().setDisplay(shortcutId, display)
            } else if (prefsKey) {
                usePinPrefs.getState().setDisplay(prefsKey, shortcutId, display)
            }
        },
        [demo, prefsKey]
    )
    const setOrder = useCallback(
        (ids: readonly string[]) => {
            if (demo) {
                useDemoViews.getState().setOrder(ids)
            } else if (prefsKey) {
                usePinPrefs.getState().setOrder(prefsKey, ids)
            }
        },
        [demo, prefsKey]
    )

    const [writing, setWriting] = useState(0)
    const write = useCallback(
        (run: (target: PinWriteTarget) => Promise<void>): Promise<void> => {
            setWriting((count) => count + 1)
            const session = sessionGeneration()
            const isCurrent = (): boolean => {
                const current = useAuthStore.getState()
                return (
                    demo ||
                    (sessionGeneration() === session &&
                        current.status === 'signed_in' &&
                        current.host?.replace(/\/$/, '') === scope?.host &&
                        current.projectId === scope?.projectId)
                )
            }
            return run({ client, listKey, demo, isCurrent }).finally(() => setWriting((count) => count - 1))
        },
        [client, listKey, demo, scope]
    )
    const pin = useCallback(
        (target: PinTarget, from: PinSource) => write((list) => pinView(list, target, from)),
        [write]
    )
    const unpin = useCallback(
        (view: PinView | PinTarget, from: PinSource) => write((list) => unpinView(list, view, from)),
        [write]
    )

    const ordered = pins.data
    return {
        isPinned: (target) => pinnedKeys.has(pinTargetKey(target)),
        pin,
        unpin,
        setDisplayMode: (pin, mode) => {
            if (mode === pin.display.mode && displayPrefs[pin.shortcutId] !== undefined) {
                return 'done'
            }
            if (pin.kind === 'dashboard' && mode !== 'row' && typeof pin.display.insightId !== 'number') {
                return 'needs_tile'
            }
            setDisplay(pin.shortcutId, { ...pin.display, mode })
            trackPinDisplayChanged({ viewType: pin.kind, displayMode: mode, previousMode: pin.display.mode })
            return 'done'
        },
        chooseTile: (pin, mode, tile) => {
            if (tile.insightId === null || !tile.shortId) {
                return
            }
            setDisplay(pin.shortcutId, {
                mode,
                tileId: tile.tileId,
                insightId: tile.insightId,
                insightShortId: tile.shortId,
            })
            trackPinTileChosen({ tileKind: tile.kindLabel })
            if (mode !== pin.display.mode) {
                trackPinDisplayChanged({ viewType: pin.kind, displayMode: mode, previousMode: pin.display.mode })
            }
        },
        move: (pin, direction) => {
            const ids = (ordered ?? []).map((candidate) => candidate.shortcutId)
            const next = movedOrder(ids, pin.shortcutId, direction)
            if (next.every((id, index) => id === ids[index])) {
                return
            }
            setOrder(next)
            trackPinsReordered({ pinCount: next.length, method: 'menu' })
        },
        reorder: (shortcutIds) => {
            setOrder(shortcutIds)
            trackPinsReordered({ pinCount: shortcutIds.length, method: 'drag' })
        },
        pending: writing > 0,
    }
}

export interface PinData {
    target: InsightTarget | null
    /** The pin's freshness key, null for a Row pin. */
    itemKey: string | null
    snapshot: InsightSnapshot | undefined
    /** A request for this pin is queued or running: show the thin progress line. */
    updating: boolean
    error: ItemErrorKind | null
    /** A dashboard pin whose tile is gone: show it as a Row with "The chosen tile was removed. Choose another." */
    tileRemoved: boolean
    /** The saved range under the number, such as "Last 7 days". A pin never uses the session range. */
    rangeLabel: string | null
}

/** The data of one Number or Chart pin, as the list's refresh rules last read it. Mounting it sends nothing. */
export function usePinData(pin: PinView): PinData {
    const context = useViewsContext()
    const target = pinTarget(pin)
    const queryKey = target ? insightQueryKey(context.scope, target) : null
    const itemKey = target ? insightItemKey(context.scope, target) : null
    const snapshot = useSnapshot<InsightSnapshot>(queryKey)
    const updating = useItemUpdating(itemKey)
    const error = useItemError(itemKey)
    return {
        target,
        itemKey,
        snapshot,
        updating,
        error,
        tileRemoved: pin.kind === 'dashboard' && error === 'deleted',
        rangeLabel: snapshot ? pinRangeLabel(snapshot) : null,
    }
}

export interface RecentState {
    recent: QueryState<RecentView[]>
    list: RefreshList
}

/** Recent: views opened on this phone and dashboards this user viewed on the web, without pinned views, at most 10. */
export function useRecentViews(pinnedKeys: ReadonlySet<string>): RecentState {
    const context = useViewsContext()
    const demo = context.mode === 'demo'
    const scope = context.scope
    const server = useQuery({
        queryKey: viewsKeys.recentDashboards(scope),
        queryFn: ({ signal }) => listRead('dashboards', signal, () => fetchRecentDashboards(signal)),
        enabled: context.ready && !demo,
        staleTime: READ_FLOOR_MS,
        retry: retryListRead,
    })
    const liveDevice =
        useDeviceRecent((state) => (scope ? state.entries[projectKey(scope)] : undefined)) ?? EMPTY_RECENT
    const demoDevice = useDemoViews((state) => state.recent)
    const device = demo ? demoDevice : liveDevice
    const serverRows = server.data?.results
    const merged = useMemo(() => mergeRecent(device, serverRows ?? [], pinnedKeys), [device, serverRows, pinnedKeys])
    const { refetch, dataUpdatedAt } = server
    const list = useMemo<RefreshList>(
        () => ({
            key: 'recent',
            updatedAt: () => (demo ? Date.now() : dataUpdatedAt),
            refetch: () => (demo ? Promise.resolve() : refetch()),
        }),
        [demo, dataUpdatedAt, refetch]
    )
    let recent: QueryState<RecentView[]>
    if (context.mode === 'loading') {
        recent = loadingQuery()
    } else if (demo || server.data || server.isError || device.length > 0) {
        // A failed web read still shows the phone's own views.
        recent = successQuery(merged, { isRefetching: server.isRefetching, refetch })
    } else {
        recent = { ...loadingQuery<RecentView[]>(), refetch }
    }
    return { recent, list }
}

/** Records a view opened on this phone for Recent, once per screen, when its name is known. */
export function useRecordRecentView(entry: Omit<DeviceRecentEntry, 'viewedAt'> | null): void {
    const context = useViewsContext()
    const recorded = useRef<string | null>(null)
    const scope = context.scope
    const demo = context.mode === 'demo'
    const kind = entry?.kind
    const ref = entry?.ref ?? null
    const name = entry?.name
    useEffect(() => {
        if (!kind || !name) {
            return
        }
        const id = `${kind}:${ref ?? ''}`
        if (recorded.current === id) {
            return
        }
        recorded.current = id
        const value: DeviceRecentEntry = { kind, ref, name, viewedAt: new Date().toISOString() }
        if (demo) {
            useDemoViews.getState().recordRecent(value)
        } else if (scope) {
            useDeviceRecent.getState().record(projectKey(scope), value)
        }
    }, [kind, ref, name, demo, scope])
}

const VIEWABILITY_CONFIG = { itemVisiblePercentThreshold: 10 }

export interface Visibility {
    /** Undefined until the list reports what it shows. */
    visibleKeys: ReadonlySet<string> | undefined
    /** A stable callback for `FlatList` / `SectionList`. */
    onViewableItemsChanged: (info: { viewableItems: ViewToken[] }) => void
    viewabilityConfig: typeof VIEWABILITY_CONFIG
}

/** Tracks which list rows are on screen. `keyOf` maps a row's item to its freshness key, or null. */
export function useVisibility(keyOf: (item: unknown) => string | null): Visibility {
    const [visibleItems, setVisibleItems] = useState<readonly unknown[] | undefined>(undefined)
    const onViewableItemsChanged = useRef((info: { viewableItems: ViewToken[] }) => {
        setVisibleItems(info.viewableItems.map((token) => token.item))
    }).current
    // A resolved display can give a visible Row pin a freshness key without another viewability callback.
    const visibleKeys = visibleItems
        ? new Set(
              visibleItems.flatMap((item) => {
                  const key = keyOf(item)
                  return key ? [key] : []
              })
          )
        : undefined
    return { visibleKeys, onViewableItemsChanged, viewabilityConfig: VIEWABILITY_CONFIG }
}

export interface ViewsListState {
    pins: QueryState<PinView[]>
    pinsTruncated: boolean
    recent: QueryState<RecentView[]>
    pinnedKeys: ReadonlySet<string>
    /** The automatic Number or Chart displays this list resolved, keyed by shortcut id. */
    automaticDisplays: PinDisplayPrefs
    /** The displays chosen on this phone, keyed by shortcut id. */
    displayPrefs: PinDisplayPrefs
    refresh: ViewRefresh
    /** Pass to the list. Rows whose item is a `PinView` count as pins. */
    onViewableItemsChanged: Visibility['onViewableItemsChanged']
    viewabilityConfig: Visibility['viewabilityConfig']
}

/** Everything the Views list needs: pins, Recent, and the list's refresh rules over the visible Number and Chart pins. */
export function useViewsList(): ViewsListState {
    const context = useViewsContext()
    const { pins: originalPins, displayPrefs, truncated, list: pinList } = usePins({ refetchOnMount: true })
    const pinnedKeys = usePinnedKeys()
    const { recent, list: recentList } = useRecentViews(pinnedKeys)
    const { displays, list: displaysList } = useSmartPinDisplays(originalPins.data, displayPrefs)
    const pinData = useMemo(
        () => (originalPins.data ? resolvePinDisplays(originalPins.data, displayPrefs, displays) : undefined),
        [originalPins.data, displayPrefs, displays]
    )
    const pins = pinData ? { ...originalPins, data: pinData } : originalPins
    const items = useMemo(() => {
        const result = (pinData ?? []).flatMap((pin) => {
            const target = pinTarget(pin)
            if (!target) {
                return []
            }
            const item = insightItem(context.item, target)
            return [
                target.dashboardRef
                    ? {
                          ...item,
                          openDue: () =>
                              isDue(item.snapshot()) ||
                              !hasGoodValue(item.snapshot()) ||
                              cacheTargetPassed(item.snapshot()),
                      }
                    : item,
            ]
        })
        const seen = new Set<string>()
        return result.filter((item) => {
            if (seen.has(item.key)) {
                return false
            }
            seen.add(item.key)
            return true
        })
    }, [pinData, context.item])
    const keyByPin = useMemo(() => {
        const keys = new Map<string, string>()
        for (const pin of pinData ?? []) {
            const target = pinTarget(pin)
            if (target) {
                keys.set(pin.shortcutId, insightItemKey(context.scope, target))
            }
        }
        return keys
    }, [pinData, context.scope])
    const visibility = useVisibility((item) => {
        const shortcutId = (item as Partial<PinView> | null)?.shortcutId
        return shortcutId ? (keyByPin.get(shortcutId) ?? null) : null
    })
    const lists = useMemo(() => [pinList, recentList, displaysList], [pinList, recentList, displaysList])
    const refresh = useViewRefresh({
        screen: 'list',
        dataScope: context.dataScope,
        screenKey: 'list',
        items,
        visibleKeys: visibility.visibleKeys,
        lists,
        enabled: context.ready,
    })
    return {
        pins,
        pinsTruncated: truncated,
        recent,
        pinnedKeys,
        automaticDisplays: displays,
        displayPrefs,
        refresh,
        onViewableItemsChanged: visibility.onViewableItemsChanged,
        viewabilityConfig: visibility.viewabilityConfig,
    }
}
