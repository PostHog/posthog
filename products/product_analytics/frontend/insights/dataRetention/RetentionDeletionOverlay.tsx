/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from the chart scales */
import { useValues } from 'kea'
import { useMemo } from 'react'

import { type ChartScales, useChartLayout } from '@posthog/quill-charts'

import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'
import { lastDeletedBucket } from './lastDeletedBucket'

const TAG_INSET = 8
const MIN_TAG_WIDTH = 120

function deletionEdgeX(
    labels: string[],
    xScale: ChartScales['x'],
    bandWidth: ChartScales['extent'],
    deletesBefore: string
): number | null {
    const last = lastDeletedBucket(labels, deletesBefore)
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

export function RetentionDeletionOverlay(): JSX.Element | null {
    const { retention, deletionCutoffLabel } = useValues(dataRetentionBannerLogic)
    const { labels, scales, dimensions } = useChartLayout()
    const { x: xScale, extent: bandWidth } = scales
    const deletesBefore = retention?.next_deletion_before

    const edgeX = useMemo(
        () => (deletesBefore ? deletionEdgeX(labels, xScale, bandWidth, deletesBefore) : null),
        [labels, xScale, bandWidth, deletesBefore]
    )

    const { plotLeft, plotTop, plotWidth, plotHeight, width, height } = dimensions
    if (edgeX === null || !deletionCutoffLabel) {
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
            <div
                className="absolute left-0 w-max text-xs font-medium"
                style={{ bottom: height - plotTop, transform: centerBetween(x, 0, width) }}
            >
                {`Retention cutoff · ${deletionCutoffLabel}`}
            </div>
            <LemonTag
                type="warning"
                wrap
                className="absolute left-0 w-max bg-fill-warning-secondary"
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
