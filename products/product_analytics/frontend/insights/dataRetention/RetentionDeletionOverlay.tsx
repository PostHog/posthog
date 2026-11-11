/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from the chart scales */
import { useValues } from 'kea'
import { useMemo } from 'react'

import { type ChartScales, useChartLayout } from '@posthog/quill-charts'

import type { Dayjs } from 'lib/dayjs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { teamLogic } from 'scenes/teamLogic'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'
import { lastDeletedBucket } from './lastDeletedBucket'
import { type RetentionDeletionChart, showsRetentionDeletion } from './showsRetentionDeletion'

const TAG_INSET = 8
const MIN_TAG_WIDTH = 120

function deletionEdgeX(
    labels: string[],
    xScale: ChartScales['x'],
    bandWidth: ChartScales['extent'],
    cutoff: Dayjs,
    timezone: string
): number | null {
    const last = lastDeletedBucket(labels, cutoff, timezone)
    if (last === null) {
        return null
    }
    const halfBand = (bandWidth?.(labels[last]) ?? 0) / 2
    if (halfBand > 0) {
        const center = xScale(labels[last])
        return center === undefined ? null : center + halfBand
    }
    return xScale(labels[last + 1] ?? labels[last]) ?? null
}

function centerBetween(center: number, min: number, max: number): string {
    return `translateX(clamp(${min}px, calc(${center}px - 50%), calc(${max}px - 100%)))`
}

export function RetentionDeletionOverlay(chart: RetentionDeletionChart): JSX.Element | null {
    const { deletionCutoff } = useValues(dataRetentionBannerLogic)
    const { timezone } = useValues(teamLogic)
    const { labels, scales, dimensions } = useChartLayout()
    const { x: xScale, extent: bandWidth } = scales
    const cutoff = showsRetentionDeletion(chart) ? deletionCutoff : null

    const edgeX = useMemo(
        () => (cutoff ? deletionEdgeX(labels, xScale, bandWidth, cutoff, timezone) : null),
        [labels, xScale, bandWidth, cutoff, timezone]
    )

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    if (edgeX === null) {
        return null
    }
    const plotRight = plotLeft + plotWidth
    const x = Math.min(edgeX, plotRight)
    if (x <= plotLeft) {
        return null
    }

    return (
        <>
            <div
                data-attr="retention-deletion-overlay"
                className="absolute bg-fill-warning-highlight"
                style={{ left: plotLeft, top: plotTop, width: x - plotLeft, height: plotHeight }}
            />
            <div
                className="absolute border-l border-dashed border-warning"
                style={{ left: x, top: plotTop, height: plotHeight }}
            />
            <LemonTag
                type="warning"
                wrap
                className="absolute left-0 w-max bg-fill-warning-secondary text-warning"
                style={{
                    top: plotTop + TAG_INSET,
                    maxWidth: Math.max(x - plotLeft - 2 * TAG_INSET, MIN_TAG_WIDTH),
                    transform: centerBetween((plotLeft + x) / 2, plotLeft + TAG_INSET, plotRight - TAG_INSET),
                }}
            >
                Older than your retention period · may be deleted soon
            </LemonTag>
        </>
    )
}
