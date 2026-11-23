import { useValues } from 'kea'
import { useMemo } from 'react'

import { getColorVar } from 'lib/colors'

import { buildAnomalyMarkers } from 'products/product_analytics/frontend/insights/trends/shared/anomalyPointsAdapter'
import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { AnomalyBucketShading } from './AnomalyBucketShading'
import { ANOMALY_FILL_COLOR_VAR } from './anomalyChartStyle'
import { buildAnomalyScorePoints } from './anomalyScorePoints'
import { insightAnomalyScoresLogic } from './insightAnomalyScoresLogic'

export interface TrendsAnomalyScoreOverlayProps {
    insightId: number
    dateFrom?: string | null
    dateTo?: string | null
    indexedResults: IndexedTrendResult[] | undefined
    getYAxisId: (result: IndexedTrendResult) => string
    isHidden: (result: IndexedTrendResult) => boolean
}

/** Shades the buckets that anomaly scoring flagged on a trends chart. Renders inside a quill chart. */
export function TrendsAnomalyScoreOverlay({
    insightId,
    dateFrom,
    dateTo,
    indexedResults,
    getYAxisId,
    isHidden,
}: TrendsAnomalyScoreOverlayProps): JSX.Element | null {
    const { scoredSeries } = useValues(insightAnomalyScoresLogic({ insightId, dateFrom, dateTo }))

    const dataIndices = useMemo(
        () =>
            buildAnomalyMarkers(
                buildAnomalyScorePoints(scoredSeries, indexedResults ?? []),
                indexedResults,
                () => '',
                getYAxisId,
                isHidden
            ).map((marker) => marker.dataIndex),
        [scoredSeries, indexedResults, getYAxisId, isHidden]
    )

    // The same red as a flagged bucket in a row chart on the Anomalies tab.
    return dataIndices.length > 0 ? (
        <AnomalyBucketShading dataIndices={dataIndices} color={getColorVar(ANOMALY_FILL_COLOR_VAR)} />
    ) : null
}
