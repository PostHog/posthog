/* eslint-disable react/forbid-dom-props -- pixel positions come from the chart scales */
import { useChartLayout } from '@posthog/quill-charts'

import { RANGE_START_LINE_BORDER } from './anomalyChartStyle'
import { useBucketEdges } from './useBucketEdges'

export interface AnomalyRangeStartLineProps {
    /** Index into the chart labels of the first bucket of the selected range. */
    dataIndex: number
}

/** A dashed vertical line on the left edge of the first bucket of the selected range. Renders inside a quill chart. */
export function AnomalyRangeStartLine({ dataIndex }: AnomalyRangeStartLineProps): JSX.Element | null {
    const { dimensions } = useChartLayout()
    const bucketEdges = useBucketEdges()

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const left = bucketEdges(dataIndex)?.[0]
    // At or past the plot's left edge the whole chart is in the range, so a line there would mark nothing.
    if (left == null || left <= plotLeft || left > plotLeft + plotWidth) {
        return null
    }
    return (
        <div
            data-attr="anomaly-range-start-line"
            className="absolute pointer-events-none"
            style={{ left, top: plotTop, height: plotHeight, borderLeft: RANGE_START_LINE_BORDER }}
        />
    )
}
