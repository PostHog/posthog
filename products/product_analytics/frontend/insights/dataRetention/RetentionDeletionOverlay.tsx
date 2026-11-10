/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from the chart scales */
import { useValues } from 'kea'
import { useMemo } from 'react'

import { type ChartScales, useChartLayout } from '@posthog/quill-charts'

import { dataRetentionBannerLogic } from './dataRetentionBannerLogic'
import { lastDeletedBucket } from './lastDeletedBucket'

const LABEL_OFFSET = 4

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

export function RetentionDeletionOverlay(): JSX.Element | null {
    const { retention, nextDeletionLabel } = useValues(dataRetentionBannerLogic)
    const { labels, scales, dimensions } = useChartLayout()
    const { x: xScale, extent: bandWidth } = scales
    const deletesBefore = retention?.next_deletion_before

    const edgeX = useMemo(
        () => (deletesBefore ? deletionEdgeX(labels, xScale, bandWidth, deletesBefore) : null),
        [labels, xScale, bandWidth, deletesBefore]
    )

    const { plotLeft, plotTop, plotWidth, plotHeight, width } = dimensions
    if (edgeX === null || !nextDeletionLabel) {
        return null
    }
    const x = Math.min(edgeX, plotLeft + plotWidth)
    if (x <= plotLeft) {
        return null
    }
    const spaceLeft = x - plotLeft
    const spaceRight = plotLeft + plotWidth - x
    const labelPosition =
        spaceLeft > spaceRight
            ? { right: width - x + LABEL_OFFSET, top: plotTop + LABEL_OFFSET, maxWidth: spaceLeft - 2 * LABEL_OFFSET }
            : { left: x + LABEL_OFFSET, top: plotTop + LABEL_OFFSET, maxWidth: spaceRight - 2 * LABEL_OFFSET }

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
                className="absolute w-max rounded bg-surface-primary px-1 text-xs text-secondary"
                style={labelPosition}
            >
                {`Shaded events are deleted on ${nextDeletionLabel}`}
            </div>
        </>
    )
}
