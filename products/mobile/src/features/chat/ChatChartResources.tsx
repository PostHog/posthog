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
    watch: (row: string, measure: () => void) => () => void
}

const ViewportContext = createContext<ChartViewport | null>(null)
const RowContext = createContext<{ key: string; index: number; ref: RefObject<ViewInstance | null> } | null>(null)
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
        const report = (): void =>
            canvas.setVisibleKeys(
                [...store.getState().charts.keys()].filter((key) => chartVisible(store.getState(), key))
            )
        return {
            store,
            layout: (key, bounds) => {
                const rows = new Map(store.getState().rows)
                rows.set(key, bounds)
                store.setState({ rows })
                measurements.get(key)?.forEach((measure) => {
                    measure()
                })
                report()
            },
            viewport: (offset, height) => {
                store.setState({ offset, height })
                report()
            },
            chart: (key, row, bounds) => {
                const charts = new Map(store.getState().charts)
                charts.set(key, { row, ...bounds })
                store.setState({ charts })
                report()
            },
            remove: (key) => {
                const charts = new Map(store.getState().charts)
                charts.delete(key)
                store.setState({ charts })
                report()
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
    return <ViewportContext.Provider value={api}>{children}</ViewportContext.Provider>
}

export function ChatChartResources({ children }: { children: ReactNode }): ReactElement {
    const active = useIsFocused()
    return (
        <ChartCanvasBudget active={active}>
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
    const value = useMemo(() => ({ key: rowKey, index, ref }), [rowKey, index])
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
    const position = useStore(api?.store ?? outside, (state) => {
        const chart = state.charts.get(group)
        return chart ? (state.rows.get(chart.row)?.y ?? 0) + chart.y : (row?.index ?? 0)
    })
    const canvasSlot = useMemo(() => (row ? { key: group, index: position } : undefined), [row, group, position])
    const onLayout = useCallback((): void => {
        const ancestor = row?.ref.current
        if (api && row && ancestor)
            ref.current?.measureLayout(ancestor, (_x, y, _width, height) => {
                if (ref.current) api.chart(group, row.key, { y, height })
            })
    }, [api, row, group])
    useEffect(() => (row ? api?.watch(row.key, onLayout) : undefined), [api, row, onLayout])
    useEffect(() => () => api?.remove(group), [api, group])
    useEffect(() => {
        if (!visible) viewsQueue.leave(group)
        return () => viewsQueue.leave(group)
    }, [group, visible])
    return { visible, canvasSlot, group, ref, onLayout }
}

export async function queuedChartRead<T>(
    group: string,
    key: string,
    family: BudgetFamily,
    read: (signal: AbortSignal) => Promise<T>
): Promise<T> {
    let value: T | undefined
    let failure: unknown
    const result = await viewsQueue.enqueue({
        key: `chat:${group}:${key}`,
        group,
        family,
        mode: 'blocking',
        // React Query owns this card's stale time and explicit retries.
        userRetry: true,
        run: async (_mode, signal) => {
            try {
                value = await read(signal)
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
