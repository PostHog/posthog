import { type RefObject, useCallback, useEffect, useId, useMemo, useRef } from 'react'
import type { View } from 'react-native'
import { type SharedValue, useSharedValue } from 'react-native-reanimated'

import { track } from '@/lib/analytics'
import { type ChartHapticKind, chartHaptic } from '@/lib/haptics'

import type { ChartKind, ChartPoint, ChartTrackingContext } from '../types'
import { type ChartDismissReason, useChartSelectionScope } from './ChartSelectionProvider'

export type SelectMethod = 'tap' | 'drag' | 'hold' | 'accessibility'

/** Selection state on the UI thread. Index -1 = none. A and B are both set during a two-finger compare. */
export interface ChartSelectionValues {
    selA: SharedValue<number>
    selB: SharedValue<number>
    scrubbing: SharedValue<boolean>
}

/** JS callbacks the gesture worklets schedule. Stable for the chart's lifetime. */
export interface ChartSelectionEvents {
    pinned: (index: number, method: SelectMethod) => void
    dismissed: (reason: ChartDismissReason) => void
    scrubStarted: (index: number, fromHold: boolean) => void
    scrubMoved: (index: number) => void
    rangeStarted: () => void
    rangeMoved: () => void
    scrubEnded: () => void
}

export interface ChartSelection {
    id: string
    values: ChartSelectionValues
    events: ChartSelectionEvents
    /** Epoch ms of the last scroll on the screen's list, or null outside a provider. */
    listMovedAt: SharedValue<number> | null
    /** Pins a point from JS, for accessibility actions. */
    pinFromJs: (index: number, method: SelectMethod) => void
    /** Closes the tooltip from JS. */
    clear: (reason: ChartDismissReason) => void
    /** Put on the chart container: marks touches as inside this chart. */
    onTouchStart: () => void
}

interface SelectionOptions {
    selectionId?: string
    viewRef: RefObject<View | null>
    /** Changes identity when the data changes, which clears the selection. */
    dataKey: unknown
    /** The first visible series' point at an index, for `onSelect`. */
    pointAt: (index: number) => ChartPoint | null
    onSelect?: (point: ChartPoint | null) => void
    trackingContext?: ChartTrackingContext
    kind: ChartKind
    seriesCount: number
}

function useLatest<T>(value: T): RefObject<T> {
    const ref = useRef(value)
    ref.current = value
    return ref
}

/**
 * Owns one chart's selection: shared values for the gestures and the overlay, and the JS side effects (haptics,
 * `onSelect`, analytics, the screen's one-pinned-chart rule). The chart itself never re-renders on a selection change.
 */
export function useChartSelection(options: SelectionOptions): ChartSelection {
    const generatedId = useId()
    const id = options.selectionId ?? generatedId
    const scope = useChartSelectionScope()
    const selA = useSharedValue(-1)
    const selB = useSharedValue(-1)
    const scrubbing = useSharedValue(false)
    const latest = useLatest(options)
    const scopeRef = useLatest(scope)

    const values = useMemo(() => ({ selA, selB, scrubbing }), [selA, selB, scrubbing])

    const emit = useCallback(
        (point: ChartPoint | null): void => {
            latest.current.onSelect?.(point)
        },
        [latest]
    )
    const trackEvent = useCallback(
        (
            event: 'mobile_chart_point_selected' | 'mobile_chart_tooltip_dismissed' | 'mobile_chart_range_compared',
            properties: Record<string, string | number>
        ): void => {
            const context = latest.current.trackingContext
            if (context) {
                track(event, { ...properties, context })
            }
        },
        [latest]
    )
    const feel = useCallback((kind: ChartHapticKind): void => chartHaptic(kind), [])

    const events = useMemo<ChartSelectionEvents>(() => {
        const selected = (method: SelectMethod): void =>
            trackEvent('mobile_chart_point_selected', {
                method,
                chart_kind: latest.current.kind,
                series_count: latest.current.seriesCount,
            })
        return {
            pinned: (index, method) => {
                scopeRef.current?.claim(id)
                feel('tick')
                // A tap reports its point, then null, like a scrub that ends at once.
                emit(latest.current.pointAt(index))
                emit(null)
                selected(method)
            },
            dismissed: (reason) => {
                scopeRef.current?.release(id)
                trackEvent('mobile_chart_tooltip_dismissed', { reason })
            },
            scrubStarted: (index, fromHold) => {
                scopeRef.current?.claim(id)
                feel(fromHold ? 'hold' : 'tick')
                emit(latest.current.pointAt(index))
                selected(fromHold ? 'hold' : 'drag')
            },
            scrubMoved: (index) => {
                feel('tick')
                emit(latest.current.pointAt(index))
            },
            rangeStarted: () => {
                feel('range')
                trackEvent('mobile_chart_range_compared', { chart_kind: latest.current.kind })
            },
            rangeMoved: () => feel('tick'),
            scrubEnded: () => emit(null),
        }
    }, [id, emit, feel, latest, scopeRef, trackEvent])

    const clear = useCallback(
        (reason: ChartDismissReason): void => {
            if (selA.value < 0 && selB.value < 0) {
                return
            }
            selA.value = -1
            selB.value = -1
            events.dismissed(reason)
        },
        [selA, selB, events]
    )

    const pinFromJs = useCallback(
        (index: number, method: SelectMethod): void => {
            selB.value = -1
            selA.value = index
            events.pinned(index, method)
        },
        [selA, selB, events]
    )

    // The scope closes this chart's tooltip when another chart pins, on an outside tap, on scroll-away and on back.
    useEffect(() => {
        if (!scope) {
            return
        }
        return scope.register(id, {
            viewRef: latest.current.viewRef,
            dismiss: (reason) => {
                selA.value = -1
                selB.value = -1
                trackEvent('mobile_chart_tooltip_dismissed', { reason })
            },
        })
    }, [scope, id, latest, selA, selB, trackEvent])

    // New data moves the buckets under the marker, so the selection goes.
    const firstData = useRef(true)
    // biome-ignore lint/correctness/useExhaustiveDependencies: dataKey is the trigger; the effect reads nothing from it.
    useEffect(() => {
        if (firstData.current) {
            firstData.current = false
            return
        }
        if (selA.value >= 0 || selB.value >= 0) {
            clear('data')
            emit(null)
        }
    }, [options.dataKey])

    const onTouchStart = useCallback((): void => scopeRef.current?.markTouch(id), [scopeRef, id])

    return {
        id,
        values,
        events,
        listMovedAt: scope?.listMovedAt ?? null,
        pinFromJs,
        clear,
        onTouchStart,
    }
}
