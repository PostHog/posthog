import { useCallback, useEffect, useMemo, useState } from 'react'
import { type AccessibilityActionEvent, AccessibilityInfo, type AccessibilityProps } from 'react-native'
import { useAnimatedReaction, useSharedValue } from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { snapToValue } from '../chartMath'
import { bucketDates, isCompareSeries, tooltipContent, tooltipPoint } from '../chartSeries'
import type { ChartSelection } from '../selection/useChartSelection'
import type { ChartAccessibilityAction, ChartInterval, ChartKind, ChartSeries, ChartTooltipPoint } from '../types'

interface ChartAccessibilityInput {
    label: string
    kind: ChartKind
    summary?: string
    series: ChartSeries[]
    hiddenKeys: readonly string[]
    interval: ChartInterval
    formatValue: (value: number) => string
    dataUntil?: number
    mask: number[]
    selection: ChartSelection
    onPressTooltip?: (point: ChartTooltipPoint) => void
    actions?: readonly ChartAccessibilityAction[]
}

export interface ChartAccessibilityProps extends AccessibilityProps {
    onAccessibilityAction: (event: AccessibilityActionEvent) => void
    onAccessibilityEscape: () => void
}

const SHOW_DETAILS = 'showDetails'

function latestValue(series: readonly ChartSeries[]): number | undefined {
    const primary = series.find((s) => !isCompareSeries(s))
    return primary ? [...primary.points].reverse().find((point) => Number.isFinite(point.value))?.value : undefined
}

/** The next selectable bucket in a direction. With nothing selected, both directions start at the latest bucket. */
function step(mask: readonly number[], from: number, direction: 1 | -1): number {
    if (from < 0) {
        return snapToValue(mask, mask.length - 1)
    }
    for (let index = from + direction; index >= 0 && index < mask.length; index += direction) {
        if (Number.isFinite(mask[index])) {
            return index
        }
    }
    return from
}

/**
 * One adjustable element for the whole chart, so VoiceOver reads a summary instead of each tick label. Swipe up or
 * down moves one bucket, shows the same marker and tooltip a sighted helper sees, and reads the tooltip as the value.
 */
export function useChartAccessibility(input: ChartAccessibilityInput): ChartAccessibilityProps {
    const { label, kind, summary, series, hiddenKeys, interval, formatValue, dataUntil, mask, selection } = input
    const { onPressTooltip, actions } = input
    const [index, setIndex] = useState(-1)
    const screenReader = useSharedValue(false)

    useEffect(() => {
        const update = (enabled: boolean): void => {
            screenReader.value = enabled
        }
        AccessibilityInfo.isScreenReaderEnabled()
            .then(update)
            .catch(() => undefined)
        const subscription = AccessibilityInfo.addEventListener('screenReaderChanged', update)
        return () => subscription.remove()
    }, [screenReader])

    // Mirrors touch selections into the value only while a screen reader runs, so scrubs do not re-render the chart.
    const { selA } = selection.values
    useAnimatedReaction(
        () => (screenReader.value ? selA.value : null),
        (current, previous) => {
            if (current !== null && current !== previous) {
                scheduleOnRN(setIndex, current)
            }
        },
        [selA, screenReader]
    )

    const valueText = useMemo(() => {
        const point = index >= 0 ? tooltipPoint(series, hiddenKeys, index, interval) : null
        if (!point) {
            return undefined
        }
        const content = tooltipContent(point, {
            formatValue,
            compact: false,
            maxRows: Number.POSITIVE_INFINITY,
            dataUntil,
        })
        const rows = content.rows.map((row) => `${row.label} ${formatValue(row.value)}`).join(', ')
        const parts = [content.header, rows, content.compare?.previous, content.compare?.change, content.note]
        return parts.filter((part): part is string => Boolean(part)).join('. ')
    }, [index, series, hiddenKeys, interval, formatValue, dataUntil])

    const latest = latestValue(series)
    const defaultSummary =
        latest === undefined ? `${label}, ${kind} chart.` : `${label}, ${kind} chart. Latest ${formatValue(latest)}.`

    const move = useCallback(
        (direction: 1 | -1): void => {
            const from = selection.values.selA.value
            const next = step(mask, from, direction)
            if (next >= 0 && next !== from) {
                selection.pinFromJs(next, 'accessibility')
            }
            setIndex(next)
        },
        [mask, selection]
    )

    const onAccessibilityAction = useCallback(
        (event: AccessibilityActionEvent): void => {
            const name = event.nativeEvent.actionName
            if (name === 'increment') {
                move(1)
            } else if (name === 'decrement') {
                move(-1)
            } else if (name === SHOW_DETAILS) {
                const at = index >= 0 ? index : snapToValue(mask, mask.length - 1)
                const details = at >= 0 ? tooltipPoint(series, hiddenKeys, at, interval) : null
                if (details) {
                    onPressTooltip?.(details)
                }
            } else {
                actions?.find((action) => action.name === name)?.onAction()
            }
        },
        [move, index, mask, series, hiddenKeys, interval, onPressTooltip, actions]
    )

    const accessibilityActions = useMemo(
        () => [
            { name: 'increment' },
            { name: 'decrement' },
            ...(onPressTooltip ? [{ name: SHOW_DETAILS, label: 'Show details' }] : []),
            ...(actions ?? []).map(({ name, label: actionLabel }) => ({ name, label: actionLabel })),
        ],
        [onPressTooltip, actions]
    )

    return {
        accessible: true,
        accessibilityRole: 'adjustable',
        accessibilityLabel: summary ?? defaultSummary,
        accessibilityValue: valueText ? { text: valueText } : undefined,
        accessibilityHint: bucketDates(series).length > 1 ? 'Swipe up or down to move between points.' : undefined,
        accessibilityActions,
        onAccessibilityAction,
        onAccessibilityEscape: () => selection.clear('back'),
    }
}
