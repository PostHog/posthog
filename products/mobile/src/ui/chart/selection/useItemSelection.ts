import { type RefObject, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { View } from 'react-native'

import { track } from '@/lib/analytics'
import { chartHaptic } from '@/lib/haptics'

import type { ChartTrackingContext } from '../types'
import { type ChartDismissReason, useChartSelectionScope } from './ChartSelectionProvider'
import type { SelectMethod } from './useChartSelection'

/** The charts drawn as rows, for the `chart_kind` of the `mobile_chart_*` events. */
export type ItemChartKind = 'funnel' | 'retention' | 'bar_list' | 'table'

export interface ItemSelection {
    /** -1 when nothing is selected. */
    selected: number
    /** A tap: selects the item, or closes it when it is the selected one. */
    toggle: (index: number) => void
    select: (index: number, method: SelectMethod) => void
    clear: (reason: ChartDismissReason) => void
    viewRef: RefObject<View | null>
    /** Put on the chart container: marks touches as inside this chart. */
    onTouchStart: () => void
}

interface ItemSelectionOptions {
    selectionId?: string
    kind: ItemChartKind
    seriesCount: number
    /** Changes identity when the data changes, which clears the selection. */
    dataKey: unknown
    trackingContext?: ChartTrackingContext
}

/**
 * The selection of a chart drawn as rows. It follows the same screen rules as a line or bar chart: one selected chart
 * per screen, closed by a tap outside, by scrolling it away and by Android back, with the same haptic and events.
 */
export function useItemSelection(options: ItemSelectionOptions): ItemSelection {
    const generatedId = useId()
    const id = options.selectionId ?? generatedId
    const scope = useChartSelectionScope()
    const [selected, setSelected] = useState(-1)
    const selectedRef = useRef(-1)
    const viewRef = useRef<View>(null)
    const latest = useRef(options)
    latest.current = options

    const update = useCallback((index: number): void => {
        selectedRef.current = index
        setSelected(index)
    }, [])

    const trackEvent = useCallback(
        (
            event: 'mobile_chart_point_selected' | 'mobile_chart_tooltip_dismissed',
            properties: Record<string, string | number>
        ) => {
            const context = latest.current.trackingContext
            if (context) {
                track(event, { ...properties, context })
            }
        },
        []
    )

    const select = useCallback(
        (index: number, method: SelectMethod): void => {
            if (index === selectedRef.current) {
                return
            }
            scope?.claim(id)
            chartHaptic('tick')
            update(index)
            trackEvent('mobile_chart_point_selected', {
                method,
                chart_kind: latest.current.kind,
                series_count: latest.current.seriesCount,
            })
        },
        [scope, id, update, trackEvent]
    )

    const clear = useCallback(
        (reason: ChartDismissReason): void => {
            if (selectedRef.current < 0) {
                return
            }
            update(-1)
            scope?.release(id)
            trackEvent('mobile_chart_tooltip_dismissed', { reason })
        },
        [scope, id, update, trackEvent]
    )

    const toggle = useCallback(
        (index: number): void => {
            if (index === selectedRef.current) {
                clear('tap_again')
            } else {
                select(index, 'tap')
            }
        },
        [clear, select]
    )

    useEffect(() => {
        if (!scope) {
            return
        }
        return scope.register(id, {
            viewRef,
            dismiss: (reason) => {
                update(-1)
                trackEvent('mobile_chart_tooltip_dismissed', { reason })
            },
        })
    }, [scope, id, update, trackEvent])

    const firstData = useRef(true)
    // biome-ignore lint/correctness/useExhaustiveDependencies: dataKey is the trigger; the effect reads nothing from it.
    useEffect(() => {
        if (firstData.current) {
            firstData.current = false
            return
        }
        clear('data')
    }, [options.dataKey])

    const onTouchStart = useCallback((): void => scope?.markTouch(id), [scope, id])

    return useMemo(
        () => ({ selected, toggle, select, clear, viewRef, onTouchStart }),
        [selected, toggle, select, clear, onTouchStart]
    )
}
