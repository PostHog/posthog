import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { getColorVar } from 'lib/colors'

import type { InsightLogicProps } from '~/types'

import { buildAnomalyMarkers } from 'products/product_analytics/frontend/insights/trends/shared/anomalyPointsAdapter'
import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { AnomalyBucketShading } from './AnomalyBucketShading'
import { ANOMALY_FILL_COLOR_VAR } from './anomalyChartStyle'
import { buildAnomalyScorePoints, seriesToIsolate } from './anomalyScorePoints'
import { claimAnomalySeriesIsolation } from './anomalyScoresParam'
import { insightAnomalyScoresLogic } from './insightAnomalyScoresLogic'

export interface TrendsAnomalyScoreOverlayProps {
    insightId: number
    insightProps: InsightLogicProps
    dateFrom?: string | null
    dateTo?: string | null
    /** The series of the Anomalies tab row. The chart shows only this series when it opens. */
    seriesKey?: string | null
    indexedResults: IndexedTrendResult[] | undefined
    getYAxisId: (result: IndexedTrendResult) => string
    isHidden: (result: IndexedTrendResult) => boolean
}

/** Shades the buckets that anomaly scoring flagged on a trends chart. Renders inside a quill chart. */
export function TrendsAnomalyScoreOverlay({
    insightId,
    insightProps,
    dateFrom,
    dateTo,
    seriesKey,
    indexedResults,
    getYAxisId,
    isHidden,
}: TrendsAnomalyScoreOverlayProps): JSX.Element | null {
    const { scoredSeries } = useValues(insightAnomalyScoresLogic({ insightId, dateFrom, dateTo, seriesKey }))
    const { toggleOtherSeriesHidden } = useActions(trendsDataLogic(insightProps))

    useEffect(() => {
        if (!seriesKey) {
            return
        }
        const result = seriesToIsolate(scoredSeries, seriesKey, indexedResults ?? [], isHidden)
        // The hidden state goes into the unsaved query of the page, as a hand toggle in the results table does.
        if (result && claimAnomalySeriesIsolation(insightId, seriesKey)) {
            toggleOtherSeriesHidden(result)
        }
    }, [insightId, seriesKey, scoredSeries, indexedResults, isHidden, toggleOtherSeriesHidden])

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
