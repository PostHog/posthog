import { type ReactElement, useCallback, useState } from 'react'
import type { LayoutChangeEvent } from 'react-native'
import { useAnimatedReaction } from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { CHART_TOOLTIP_TEST_ID, ChartTooltip, TOOLTIP_MAX_WIDTH } from './ChartTooltip'
import type { ChartGeometry } from './chartGeometry'
import { tooltipLeft } from './chartMath'
import { rangeContent, TOOLTIP_MAX_ROWS, tooltipContent, tooltipPoint } from './chartSeries'
import { CHART_RANGE_TOOLTIP_TEST_ID, RangeTooltip } from './RangeTooltip'
import type { ChartSelectionValues } from './selection/useChartSelection'
import type { ChartInterval, ChartSeries, ChartTooltipPoint, ChartVariant } from './types'

const TOOLTIP_GAP = 12

interface Shown {
    a: number
    b: number
    scrubbing: boolean
}

interface ChartOverlayProps {
    selection: ChartSelectionValues
    geometry: ChartGeometry
    series: ChartSeries[]
    hiddenKeys: readonly string[]
    interval: ChartInterval
    variant: ChartVariant
    formatValue: (value: number) => string
    dataUntil?: number
    onPressTooltip?: (point: ChartTooltipPoint) => void
}

/**
 * The tooltip layer. It mirrors the selection shared values into React state, so a scrub re-renders only this
 * component and never the canvas.
 */
export function ChartOverlay({
    selection,
    geometry,
    series,
    hiddenKeys,
    interval,
    variant,
    formatValue,
    dataUntil,
    onPressTooltip,
}: ChartOverlayProps): ReactElement | null {
    const [shown, setShown] = useState<Shown>({ a: -1, b: -1, scrubbing: false })
    const [tooltipWidth, setTooltipWidth] = useState(0)
    const { selA, selB, scrubbing } = selection

    useAnimatedReaction(
        () => ({ a: selA.value, b: selB.value, scrubbing: scrubbing.value }),
        (current, previous) => {
            if (
                previous === null ||
                current.a !== previous.a ||
                current.b !== previous.b ||
                current.scrubbing !== previous.scrubbing
            ) {
                scheduleOnRN(setShown, current)
            }
        },
        [selA, selB, scrubbing]
    )

    const onLayout = useCallback((event: LayoutChangeEvent): void => {
        setTooltipWidth(event.nativeEvent.layout.width)
    }, [])

    const { width, plot, xs } = geometry
    const maxWidth = Math.min(TOOLTIP_MAX_WIDTH, width)

    if (shown.a >= 0 && shown.b >= 0) {
        const content = rangeContent(series, hiddenKeys, shown.a, shown.b, interval, formatValue)
        if (!content) {
            return null
        }
        const middle = ((xs[shown.a] ?? 0) + (xs[shown.b] ?? 0)) / 2
        const left = Math.max(0, Math.min(width - tooltipWidth, middle - tooltipWidth / 2))
        return (
            <RangeTooltip
                content={content}
                left={left}
                top={plot.top + 2}
                maxWidth={maxWidth}
                onLayout={onLayout}
                testID={CHART_RANGE_TOOLTIP_TEST_ID}
            />
        )
    }
    if (shown.a < 0) {
        return null
    }
    const point = tooltipPoint(series, hiddenKeys, shown.a, interval)
    const anchorX = xs[shown.a]
    if (!point || anchorX === undefined) {
        return null
    }
    const content = tooltipContent(point, {
        formatValue,
        compact: variant === 'compact',
        maxRows: variant === 'fullscreen' ? Number.POSITIVE_INFINITY : TOOLTIP_MAX_ROWS,
        dataUntil,
    })
    // While a finger scrubs, the tooltip only follows; it takes taps once the point is pinned.
    const onPress = onPressTooltip && !shown.scrubbing ? () => onPressTooltip(point) : undefined
    return (
        <ChartTooltip
            content={content}
            formatValue={formatValue}
            left={tooltipLeft(anchorX, tooltipWidth, width, TOOLTIP_GAP)}
            top={plot.top}
            maxWidth={maxWidth}
            onPress={onPress}
            onLayout={onLayout}
            testID={CHART_TOOLTIP_TEST_ID}
        />
    )
}
