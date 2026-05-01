import { useActions } from 'kea'
import { useCallback, useEffect, useRef } from 'react'
import { match } from 'ts-pattern'
import useResizeObserver from 'use-resize-observer'

import { cn } from 'lib/utils/css-classes'

import { useSparklineOptions } from '../../hooks/use-sparkline-options'
import { errorTrackingVolumeSparklineLogic } from './errorTrackingVolumeSparklineLogic'
import type {
    SparklineData,
    SparklineDatum,
    SparklineEvent,
    VolumeSparklineLayout,
    VolumeSparklineXAxisMode,
} from './types'
import { renderVolumeSparkline } from './volumeSparklineRender'

export type { VolumeSparklineLayout, VolumeSparklineXAxisMode } from './types'

export type VolumeSparklineProps = {
    data: SparklineData
    layout: VolumeSparklineLayout
    sparklineKey: string
    xAxis?: VolumeSparklineXAxisMode
    className?: string
    events?: SparklineEvent<string>[]
    onRangeSelect?: (startDate: Date, endDate: Date) => void
    onSpikeClick?: (datum: SparklineDatum, clientX: number, clientY: number) => void
}

export function VolumeSparkline({
    sparklineKey,
    data,
    layout,
    xAxis = 'none',
    className,
    events = [],
    onRangeSelect,
    onSpikeClick,
}: VolumeSparklineProps): JSX.Element {
    const { setHoveredBin, setHoveredEvent } = useActions(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const svgRef = useRef<SVGSVGElement>(null)
    const { height, width, ref: containerRef } = useResizeObserver({ box: 'content-box' })

    const onHoverChange = useCallback(
        (index: number | null, datum: SparklineDatum | null) => {
            if (index == null || datum == null) {
                setHoveredBin(null)
            } else {
                setHoveredBin({ index, datum })
            }
        },
        [setHoveredBin]
    )

    const onEventHoverChange = useCallback(
        (e: SparklineEvent<string> | null) => {
            setHoveredEvent(e)
        },
        [setHoveredEvent]
    )

    const chartStyle = useSparklineOptions(
        match(layout)
            .with('compact', () => ({ minBarHeight: 2, borderRadius: 3, eventLabelHeight: 0 }))
            .with('detailed', () => ({
                minBarHeight: 10,
                borderRadius: 4,
                eventLabelHeight: events.length > 0 ? 20 : 0,
            }))
            .exhaustive(),
        [layout, events.length]
    )

    const barWidthFraction = layout === 'compact' ? 0.78 : 0.9

    useEffect(() => {
        const svg = svgRef.current
        if (!svg || width == null || height == null) {
            return
        }

        const cleanup = renderVolumeSparkline(svg, {
            sparklineKey,
            data,
            width,
            height,
            xAxis,
            backgroundColor: chartStyle.backgroundColor,
            hoverBackgroundColor: chartStyle.hoverBackgroundColor,
            axisColor: chartStyle.axisColor,
            borderRadius: chartStyle.borderRadius,
            minBarHeight: chartStyle.minBarHeight,
            eventLabelHeight: chartStyle.eventLabelHeight,
            barWidthFraction,
            onHoverChange,
            events,
            onEventHoverChange,
            eventLabelPaddingX: chartStyle.eventLabelPaddingX,
            eventLabelPaddingY: chartStyle.eventLabelPaddingY,
            eventMinSpace: chartStyle.eventMinSpace,
            onRangeSelect,
            onSpikeClick,
        })

        return cleanup
    }, [
        data,
        width,
        height,
        xAxis,
        chartStyle.backgroundColor,
        chartStyle.hoverBackgroundColor,
        chartStyle.axisColor,
        chartStyle.borderRadius,
        chartStyle.minBarHeight,
        chartStyle.eventLabelHeight,
        chartStyle.eventLabelPaddingX,
        chartStyle.eventLabelPaddingY,
        chartStyle.eventMinSpace,
        barWidthFraction,
        onHoverChange,
        events,
        onEventHoverChange,
        onRangeSelect,
        onSpikeClick,
        sparklineKey,
    ])

    const paddingClass = match(layout)
        .with('compact', () => 'p-1')
        .with('detailed', () => 'p-0')
        .exhaustive()

    return (
        <div
            ref={containerRef}
            className={cn('h-full w-full min-h-0 min-w-0 overflow-hidden', paddingClass, className)}
        >
            <svg ref={svgRef} className="block overflow-visible" height="100%" width="100%" />
        </div>
    )
}
