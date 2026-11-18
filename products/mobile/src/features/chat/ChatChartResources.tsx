import type { Query } from '@tanstack/react-query'
import { useIsFocused } from 'expo-router'
import {
    createContext,
    type ReactElement,
    type ReactNode,
    type RefObject,
    useCallback,
    useContext,
    useEffect,
    useId,
    useLayoutEffect,
    useMemo,
    useRef,
} from 'react'
import type { LayoutChangeEvent, NativeScrollEvent, NativeSyntheticEvent, ViewInstance } from 'react-native'
import { View } from 'react-native'
import { createStore, type StoreApi, useStore } from 'zustand'
import type { BudgetFamily } from '@/api/budget'
import { BudgetExceededError } from '@/api/budget'
import { viewsQueue } from '@/features/views/refreshQueue'
import { abortError } from '@/lib/abort'
import { ChartCanvasBudget, useCanvasBudgetViewport } from '@/ui/chart/budget/ChartCanvasBudget'
import type { ChartCanvasSlot } from '@/ui/chart/types'

interface RowBounds {
    y: number
    height: number
}
interface ViewportState {
    offset: number
    height: number
    active: boolean
    rows: ReadonlyMap<string, RowBounds>
    charts: ReadonlyMap<string, RowBounds & { row: string }>
}
interface ChartViewport {
    store: StoreApi<ViewportState>
    layout: (key: string, bounds: RowBounds) => void
    viewport: (offset: number, height: number) => void
    chart: (key: string, row: string, bounds: RowBounds) => void
    remove: (key: string) => void
    removeRow: (key: string) => void
    dispose: () => void
    watch: (row: string, measure: () => void) => () => void
}

const ViewportContext = createContext<ChartViewport | null>(null)
const RowContext = createContext<{
    key: string
    index: number
    ref: RefObject<ViewInstance | null>
    slots: Map<string, number>
    nextSlot: { current: number }
} | null>(null)
const outside = createStore<ViewportState>(() => ({
    offset: 0,
    height: 0,
    active: true,
    rows: new Map(),
    charts: new Map(),
}))

function chartVisible(state: ViewportState, key: string): boolean {
    const chart = state.charts.get(key)
    const row = chart && state.rows.get(chart.row)
    return (
        state.active &&
        !!row &&
        !!chart &&
        state.height > 0 &&
        row.y + chart.y < state.offset + state.height &&
        row.y + chart.y + chart.height > state.offset
    )
}

function ChartViewportProvider({ active, children }: { active: boolean; children: ReactNode }): ReactElement {
    const canvas = useCanvasBudgetViewport()
    const api = useMemo<ChartViewport>(() => {
        const store = createStore<ViewportState>(() => ({
            offset: 0,
            height: 0,
            active: true,
            rows: new Map(),
            charts: new Map(),
        }))
        const measurements = new Map<string, Set<() => void>>()
        const rowsPending = new Map<string, RowBounds | null>()
        const chartsPending = new Map<string, (RowBounds & { row: string }) | null>()
        let frame: number | null = null
        let offset = 0
        let height = 0
        const report = (): void =>
            canvas.setVisibleKeys(
                [...store.getState().charts.keys()].filter((key) => chartVisible(store.getState(), key))
            )
        const schedule = (): void => {
            if (frame !== null) return
            frame = requestAnimationFrame(() => {
                frame = null
                const rows = new Map(store.getState().rows)
                const charts = new Map(store.getState().charts)
                for (const [key, value] of rowsPending) {
                    if (value) rows.set(key, value)
                    else rows.delete(key)
                }
                for (const [key, value] of chartsPending) {
                    if (value && rows.has(value.row)) charts.set(key, value)
                    else charts.delete(key)
                }
                for (const [key, value] of charts) if (!rows.has(value.row)) charts.delete(key)
                rowsPending.clear()
                chartsPending.clear()
                store.setState({ rows, charts, offset, height })
                report()
            })
        }
        return {
            store,
            layout: (key, bounds) => {
                rowsPending.set(key, bounds)
                measurements.get(key)?.forEach((measure) => {
                    measure()
                })
                schedule()
            },
            viewport: (nextOffset, nextHeight) => {
                offset = nextOffset
                height = nextHeight
                store.setState({ offset, height })
                report()
            },
            chart: (key, row, bounds) => {
                chartsPending.set(key, { row, ...bounds })
                schedule()
            },
            remove: (key) => {
                chartsPending.set(key, null)
                schedule()
            },
            removeRow: (key) => {
                rowsPending.set(key, null)
                measurements.delete(key)
                schedule()
            },
            dispose: () => {
                if (frame !== null) cancelAnimationFrame(frame)
                frame = null
                rowsPending.clear()
                chartsPending.clear()
                measurements.clear()
            },
            watch: (row, measure) => {
                const watchers = measurements.get(row) ?? new Set()
                measurements.set(row, watchers)
                watchers.add(measure)
                return () => {
                    watchers.delete(measure)
                    if (watchers.size === 0) measurements.delete(row)
                }
            },
        }
    }, [canvas])
    useEffect(() => {
        api.store.setState({ active })
        api.viewport(api.store.getState().offset, api.store.getState().height)
    }, [api, active])
    useEffect(() => () => api.dispose(), [api])
    return <ViewportContext.Provider value={api}>{children}</ViewportContext.Provider>
}

export function ChatChartResources({ children }: { children: ReactNode }): ReactElement {
    const active = useIsFocused()
    return (
        <ChartCanvasBudget active={active} prioritizeVisible>
            <ChartViewportProvider active={active}>{children}</ChartViewportProvider>
        </ChartCanvasBudget>
    )
}

export function ChatChartRow({
    rowKey,
    index,
    children,
}: {
    rowKey: string
    index: number
    children: ReactNode
}): ReactElement {
    const api = useContext(ViewportContext)
    const ref = useRef<ViewInstance>(null)
    const slots = useRef(new Map<string, number>()).current
    const nextSlot = useRef(0)
    const value = useMemo(() => ({ key: rowKey, index, ref, slots, nextSlot }), [rowKey, index, slots])
    useLayoutEffect(() => () => api?.removeRow(rowKey), [api, rowKey])
    return (
        <RowContext.Provider value={value}>
            <View ref={ref} collapsable={false} onLayout={({ nativeEvent }) => api?.layout(rowKey, nativeEvent.layout)}>
                {children}
            </View>
        </RowContext.Provider>
    )
}

export function useChatChartViewport(): {
    onLayout: (event: LayoutChangeEvent) => void
    onScroll: (event: NativeSyntheticEvent<NativeScrollEvent>) => void
} {
    const api = useContext(ViewportContext)
    return {
        onLayout: ({ nativeEvent }) => api?.viewport(api.store.getState().offset, nativeEvent.layout.height),
        onScroll: ({ nativeEvent }) => api?.viewport(nativeEvent.contentOffset.y, nativeEvent.layoutMeasurement.height),
    }
}

export function useChatChartResource(): {
    visible: boolean
    canvasSlot?: ChartCanvasSlot
    group: string
    ref: RefObject<ViewInstance | null>
    onLayout: () => void
} {
    const api = useContext(ViewportContext)
    const row = useContext(RowContext)
    const group = useId()
    const ref = useRef<ViewInstance>(null)
    const visible = useStore(api?.store ?? outside, (state) => !row || chartVisible(state, group))
    const position = useMemo(() => {
        if (!row) return 0
        let ordinal = row.slots.get(group)
        if (ordinal === undefined) {
            ordinal = row.nextSlot.current++
            row.slots.set(group, ordinal)
        }
        return row.index + ordinal / (ordinal + 1)
    }, [row, group])
    const canvasSlot = useMemo(() => (row ? { key: group, index: position } : undefined), [row, group, position])
    const measurement = useRef(0)
    const onLayout = useCallback((): void => {
        const version = ++measurement.current
        const ancestor = row?.ref.current
        if (api && row && ancestor)
            ref.current?.measureLayout(ancestor, (_x, y, _width, height) => {
                if (ref.current && version === measurement.current) api.chart(group, row.key, { y, height })
            })
    }, [api, row, group])
    useEffect(() => (row ? api?.watch(row.key, onLayout) : undefined), [api, row, onLayout])
    useLayoutEffect(
        () => () => {
            measurement.current++
            row?.slots.delete(group)
            api?.remove(group)
        },
        [api, row, group]
    )
    return { visible, canvasSlot, group, ref, onLayout }
}

const readGroups = new WeakMap<Query, string>()
const reads = new WeakMap<Query, Promise<unknown>>()
let nextReadGroup = 0

function readGroup(query: Query): string {
    let group = readGroups.get(query)
    if (!group) {
        group = `chat-read:${++nextReadGroup}`
        readGroups.set(query, group)
    }
    return group
}

export function releaseChartRead(query: Query): void {
    queueMicrotask(() => {
        if (query.isActive()) return
        const group = readGroups.get(query)
        if (!group) return
        viewsQueue.leave(group)
        if (!viewsQueue.isKeyBusy(group)) reads.delete(query)
    })
}

export function queuedChartRead<T>(
    query: Query,
    family: BudgetFamily,
    read: (signal: AbortSignal) => Promise<T>
): Promise<T> {
    const previous = reads.get(query)
    if (previous) return previous as Promise<T>
    const group = readGroup(query)
    const promise = runChartRead(group, family, read).finally(() => {
        if (reads.get(query) === promise) reads.delete(query)
    })
    reads.set(query, promise)
    return promise
}

async function runChartRead<T>(
    group: string,
    family: BudgetFamily,
    read: (signal: AbortSignal) => Promise<T>
): Promise<T> {
    let value: T | undefined
    let failure: unknown
    const result = await viewsQueue.enqueue({
        key: group,
        group,
        family,
        mode: 'blocking',
        // React Query owns this card's stale time and explicit retries.
        userRetry: true,
        trackFreshness: false,
        run: async (_mode, signal) => {
            try {
                value = await read(signal)
                failure = undefined
                if (signal.aborted) throw abortError()
                return { status: 'ok', computed: false }
            } catch (error) {
                failure = error
                throw error
            }
        },
    })
    if (failure) throw failure
    if (result.status === 'aborted') throw abortError()
    if (result.status === 'capped') throw new BudgetExceededError(family)
    if (result.status !== 'ok') throw new Error('Chart read failed')
    return value as T
}
