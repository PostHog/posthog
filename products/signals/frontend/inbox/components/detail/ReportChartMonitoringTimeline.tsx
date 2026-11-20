/* eslint-disable react/forbid-dom-props -- chart scales determine the strip's edges */
import { useValues } from 'kea'
import { useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { teamLogic } from 'scenes/teamLogic'

import type { TrendsQuery } from '~/queries/schema/schema-general'

import type { ReportMetricChartType } from '../../utils/reportMetrics'
import { monitoringChartBucketPositioner } from '../../utils/reportMonitoringChart'
import { ReportCheckMonitoringTimeline } from './ReportCheckMonitoringTimeline'
import type { MonitoringTimeline } from './reportCheckObservations'

export const CHART_TIMELINE_HEIGHT = 12

/**
 * The Monitoring strip drawn on the chart's own x-axis, so a measurement lines up with its bucket.
 * Bars sit in bands, so the strip runs from the first band's left edge to the last band's right edge.
 * Line points sit on bucket starts, so the strip runs from the first point to the last.
 */
export function ReportChartMonitoringTimeline({
    timeline,
    type,
    interval,
}: {
    timeline: MonitoringTimeline
    type: ReportMetricChartType
    interval: NonNullable<TrendsQuery['interval']>
}): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()
    const xScale = scales.x
    const { timezone } = useValues(teamLogic)

    const bucketAt = useMemo(
        () => monitoringChartBucketPositioner(labels, timezone, interval),
        [labels, timezone, interval]
    )

    const layout = useMemo(() => {
        const centers = labels.map((label) => xScale(label))
        if (!centers.length || centers.some((center) => center == null || !Number.isFinite(center))) {
            return null
        }
        const first = centers[0] as number
        const last = centers[centers.length - 1] as number
        const bands = type === 'bar' || centers.length === 1
        const step = centers.length > 1 ? (last - first) / (centers.length - 1) : dimensions.plotWidth
        const slots = bands ? labels.length : labels.length - 1
        const positionAt = (time: number): number | null => {
            const bucket = bucketAt(time)
            return bucket ? Math.min((bucket.index + bucket.fraction) / slots, 1) : null
        }
        const parse = (iso: string | null): number => (iso ? Date.parse(iso) : NaN)
        return {
            left: bands ? first - step / 2 : first,
            width: bands ? step * centers.length : last - first,
            startPosition: positionAt(parse(timeline.startedAt)) ?? 0,
            timeline: {
                ...timeline,
                elapsed: positionAt(Math.min(timeline.now, parse(timeline.endsAt))) ?? 0,
                nextPosition: positionAt(parse(timeline.nextMeasurementAt)),
                measurements: timeline.measurements.map((measurement) => ({
                    ...measurement,
                    position: positionAt(parse(measurement.measuredAt)) ?? measurement.position,
                })),
            },
        }
    }, [xScale, labels, dimensions.plotWidth, timeline, type, bucketAt])

    if (!layout) {
        return null
    }
    return (
        <div
            // The chart overlay layer ignores the pointer; the strip opts back in for its tooltip.
            className="pointer-events-auto absolute -translate-y-1/2"
            style={{ left: layout.left, width: layout.width, top: dimensions.height - CHART_TIMELINE_HEIGHT / 2 }}
        >
            <ReportCheckMonitoringTimeline timeline={layout.timeline} startPosition={layout.startPosition} />
        </div>
    )
}
