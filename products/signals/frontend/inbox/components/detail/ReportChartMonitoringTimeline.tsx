/* eslint-disable react/forbid-dom-props -- chart scales determine the strip's edges */
import { useValues } from 'kea'
import { useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { teamLogic } from 'scenes/teamLogic'

import { monitoringChartBucketPosition } from '../../utils/reportMonitoringChart'
import { ReportCheckMonitoringTimeline } from './ReportCheckMonitoringTimeline'
import type { MonitoringTimeline } from './reportCheckObservations'

export const CHART_TIMELINE_HEIGHT = 12

/**
 * The Monitoring strip drawn on the chart's own x-axis: its edges are the first and last bucket edges,
 * and each point sits within its bucket by time, so a measurement lines up with its bar.
 */
export function ReportChartMonitoringTimeline({
    timeline,
    now,
}: {
    timeline: MonitoringTimeline
    now: number
}): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()
    const xScale = scales.x
    const { timezone } = useValues(teamLogic)

    const layout = useMemo(() => {
        const centers = labels.map((label) => xScale(label))
        if (!centers.length || centers.some((center) => center == null || !Number.isFinite(center))) {
            return null
        }
        const first = centers[0] as number
        const last = centers[centers.length - 1] as number
        const step = centers.length > 1 ? (last - first) / (centers.length - 1) : dimensions.plotWidth
        const positionAt = (time: number): number | null => {
            const bucket = monitoringChartBucketPosition(labels, time, timezone)
            return bucket ? (bucket.index + bucket.fraction) / labels.length : null
        }
        const parse = (iso: string | null): number => (iso ? Date.parse(iso) : NaN)
        return {
            left: first - step / 2,
            width: step * centers.length,
            timeline: {
                ...timeline,
                elapsed: positionAt(now) ?? 0,
                nextPosition: positionAt(parse(timeline.nextMeasurementAt)),
                measurements: timeline.measurements.map((measurement) => ({
                    ...measurement,
                    position: positionAt(parse(measurement.measuredAt)) ?? measurement.position,
                })),
            },
        }
    }, [xScale, labels, dimensions.plotWidth, timeline, now, timezone])

    if (!layout) {
        return null
    }
    return (
        <div
            // The chart overlay layer ignores the pointer; the strip opts back in for its tooltip.
            className="pointer-events-auto absolute -translate-y-1/2"
            style={{ left: layout.left, width: layout.width, top: dimensions.height - CHART_TIMELINE_HEIGHT / 2 }}
        >
            <ReportCheckMonitoringTimeline timeline={layout.timeline} />
        </div>
    )
}
