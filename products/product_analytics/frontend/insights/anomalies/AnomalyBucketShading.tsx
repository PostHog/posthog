/* eslint-disable react/forbid-dom-props -- pixel positions come from the chart scales */
import { useMemo } from 'react'

import { useChartLayout } from '@posthog/quill-charts'

import { ANOMALY_FILL_OPACITY } from './anomalyChartStyle'
import { contiguousRuns } from './anomalyScorePoints'
import { useBucketEdges } from './useBucketEdges'

// A band narrower than this is hard to see on a chart with many buckets, such as a week of hours.
const MIN_BAND_WIDTH_PX = 6

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
    opacity = ANOMALY_FILL_OPACITY,
}: AnomalyBucketShadingProps): JSX.Element | null {
    const { dimensions } = useChartLayout()
    const bucketEdges = useBucketEdges()
    const runs = useMemo(() => contiguousRuns(dataIndices), [dataIndices])

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const plotRight = plotLeft + plotWidth

    const bands: JSX.Element[] = []
    for (const [start, end] of runs) {
        const startEdges = bucketEdges(start)
        const endEdges = bucketEdges(end)
        if (startEdges == null || endEdges == null) {
            continue
        }
        let lo = startEdges[0]
        let hi = endEdges[1]
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
