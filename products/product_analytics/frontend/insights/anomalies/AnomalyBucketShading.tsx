/* eslint-disable react/forbid-dom-props -- pixel positions come from the chart scales */
import { useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { contiguousRuns } from './anomalyScorePoints'

// A band narrower than this is hard to see on a chart with many buckets, such as two weeks of hours.
const MIN_BAND_WIDTH_PX = 6
const FILL_OPACITY = 0.2

export interface AnomalyBucketShadingProps {
    /** Indices into the chart labels of the buckets to shade. */
    dataIndices: number[]
    color: string
    /** Opacity 0-1 of the fill. */
    opacity?: number
}

/** Shades the full height of the plot behind each given bucket. Renders inside a quill chart. */
export function AnomalyBucketShading({
    dataIndices,
    color,
    opacity = FILL_OPACITY,
}: AnomalyBucketShadingProps): JSX.Element | null {
    const { scales, dimensions, labels } = useChartLayout()
    const runs = useMemo(() => contiguousRuns(dataIndices), [dataIndices])

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const plotRight = plotLeft + plotWidth

    const centre = (index: number): number | null => {
        const label = labels[index]
        const x = label != null ? scales.x(label) : undefined
        return x != null && isFinite(x) ? x : null
    }
    // A bar chart gives a bucket its band width. A line chart has only points, so a bucket takes the space
    // between the midpoints to its neighbours.
    const firstX = centre(0)
    const secondX = centre(1)
    const step = firstX != null && secondX != null ? Math.abs(secondX - firstX) : plotWidth
    const halfWidth = (index: number): number => {
        const label = labels[index]
        return (scales.extent?.(label) || step) / 2
    }

    const bands: JSX.Element[] = []
    for (const [start, end] of runs) {
        const startX = centre(start)
        const endX = centre(end)
        if (startX == null || endX == null) {
            continue
        }
        let lo = startX - halfWidth(start)
        let hi = endX + halfWidth(end)
        if (hi - lo < MIN_BAND_WIDTH_PX) {
            const middle = (lo + hi) / 2
            lo = middle - MIN_BAND_WIDTH_PX / 2
            hi = middle + MIN_BAND_WIDTH_PX / 2
        }
        const left = Math.max(lo, plotLeft)
        const right = Math.min(hi, plotRight)
        if (right <= left) {
            continue
        }
        bands.push(
            <div
                key={start}
                data-attr="anomaly-bucket-shading"
                className="absolute pointer-events-none"
                style={{
                    left,
                    top: plotTop,
                    width: right - left,
                    height: plotHeight,
                    backgroundColor: color,
                    opacity,
                }}
            />
        )
    }
    return <>{bands}</>
}
