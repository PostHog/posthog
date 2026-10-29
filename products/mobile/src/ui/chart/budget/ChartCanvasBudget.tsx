import { createContext, type ReactElement, type ReactNode, useContext, useEffect, useMemo } from 'react'
import type { ViewToken } from 'react-native'
import { createStore, type StoreApi, useStore } from 'zustand'

import type { ChartCanvasSlot } from '../types'

/**
 * Each Skia canvas holds its own GPU surfaces, a few MB per chart, and victory-native and Skia have open native-memory
 * reports. A list mounts at most this many at once; the rest show a Sparkline at the same height.
 */
export const MAX_MOUNTED_CANVASES = 6

interface BudgetState {
    slots: ReadonlyMap<string, number>
    visibleKeys: readonly string[]
    active: boolean
    granted: ReadonlySet<string>
}

interface BudgetApi {
    store: StoreApi<BudgetState>
    register: (slot: ChartCanvasSlot) => () => void
    setVisibleKeys: (keys: readonly string[]) => void
    setActive: (active: boolean) => void
}

const NONE: ReadonlySet<string> = new Set()

const BudgetContext = createContext<BudgetApi | null>(null)

/**
 * The slots that get a canvas: those nearest the visible items, by list index. Inside the visible range the distance
 * is 0, and ties go to the earlier item. With no visibility reported yet, the first items win.
 */
export function grantSlots(
    slots: ReadonlyMap<string, number>,
    visibleKeys: readonly string[],
    max: number
): Set<string> {
    const visibleIndexes = visibleKeys.map((key) => slots.get(key)).filter((index) => index !== undefined)
    const first = visibleIndexes.length > 0 ? Math.min(...visibleIndexes) : 0
    const last = visibleIndexes.length > 0 ? Math.max(...visibleIndexes) : 0
    const distance = (index: number): number => (index < first ? first - index : index > last ? index - last : 0)
    const ranked = [...slots.entries()].sort(([, a], [, b]) => distance(a) - distance(b) || a - b)
    return new Set(ranked.slice(0, Math.max(0, max)).map(([key]) => key))
}

function sameSet(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
    return a.size === b.size && [...a].every((key) => b.has(key))
}

/**
 * Wrap a list of charts. Charts with a `canvasSlot` inside it share `max` canvases. `active: false` grants none, so a
 * screen under another one in a stack keeps no canvas while it is not on screen.
 */
export function ChartCanvasBudget({
    max = MAX_MOUNTED_CANVASES,
    active = true,
    children,
}: {
    max?: number
    active?: boolean
    children: ReactNode
}): ReactElement {
    const api = useMemo<BudgetApi>(() => {
        const store = createStore<BudgetState>(() => ({
            slots: new Map(),
            visibleKeys: [],
            active: true,
            granted: new Set(),
        }))
        const update = (slots: ReadonlyMap<string, number>, visibleKeys: readonly string[], on: boolean): void => {
            const granted = on ? grantSlots(slots, visibleKeys, max) : NONE
            const previous = store.getState().granted
            store.setState({ slots, visibleKeys, active: on, granted: sameSet(previous, granted) ? previous : granted })
        }
        return {
            store,
            register: ({ key, index }) => {
                const slots = new Map(store.getState().slots)
                slots.set(key, index)
                update(slots, store.getState().visibleKeys, store.getState().active)
                return () => {
                    const next = new Map(store.getState().slots)
                    next.delete(key)
                    update(next, store.getState().visibleKeys, store.getState().active)
                }
            },
            setVisibleKeys: (keys) => update(store.getState().slots, keys, store.getState().active),
            setActive: (on) => update(store.getState().slots, store.getState().visibleKeys, on),
        }
    }, [max])
    useEffect(() => {
        api.setActive(active)
    }, [api, active])
    return <BudgetContext.Provider value={api}>{children}</BudgetContext.Provider>
}

const ALWAYS = createStore<BudgetState>(() => ({ slots: new Map(), visibleKeys: [], active: true, granted: new Set() }))

/**
 * Whether this chart may mount its canvas. True outside a `ChartCanvasBudget` or without a slot. Inside one, the
 * chart waits for a grant, which arrives in the render after it registers.
 */
export function useCanvasSlot(slot: ChartCanvasSlot | undefined): boolean {
    const api = useContext(BudgetContext)
    const key = slot?.key
    const index = slot?.index
    const granted = useStore(api?.store ?? ALWAYS, (state) => (key === undefined ? true : state.granted.has(key)))
    useEffect(() => {
        if (!api || key === undefined || index === undefined) {
            return
        }
        return api.register({ key, index })
    }, [api, key, index])
    return api === null || key === undefined || granted
}

export interface CanvasBudgetViewport {
    /** Pass to a `FlatList` or `SectionList`. Item keys must match the charts' `canvasSlot.key`. */
    onViewableItemsChanged: (info: { viewableItems: ViewToken[] }) => void
    /** For lists that track visibility themselves. */
    setVisibleKeys: (keys: readonly string[]) => void
}

const NO_VIEWPORT: CanvasBudgetViewport = { onViewableItemsChanged: () => undefined, setVisibleKeys: () => undefined }

export function useCanvasBudgetViewport(): CanvasBudgetViewport {
    const api = useContext(BudgetContext)
    return useMemo(
        () =>
            api
                ? {
                      onViewableItemsChanged: ({ viewableItems }) =>
                          api.setVisibleKeys(viewableItems.map((token) => token.key)),
                      setVisibleKeys: api.setVisibleKeys,
                  }
                : NO_VIEWPORT,
        [api]
    )
}
