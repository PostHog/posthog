import { useValues } from 'kea'
import { useMemo } from 'react'

import { AnomalyPointsLayer } from '@posthog/quill-charts'

import { getColorVar } from 'lib/colors'

import { buildAnomalyMarkers } from 'products/product_analytics/frontend/insights/trends/shared/anomalyPointsAdapter'
import type { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

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

/** Marks the buckets that anomaly scoring flagged on a trends chart. Renders inside a quill chart. */
export function TrendsAnomalyScoreOverlay({
    insightId,
    dateFrom,
    dateTo,
    indexedResults,
    getYAxisId,
    isHidden,
}: TrendsAnomalyScoreOverlayProps): JSX.Element | null {
    const { scoredSeries } = useValues(insightAnomalyScoresLogic({ insightId, dateFrom, dateTo }))

    const markers = useMemo(() => {
        // The same mark as a row chart on the Anomalies tab, so a flagged bucket looks the same in both places.
        const color = getColorVar('danger')
        return buildAnomalyMarkers(
            buildAnomalyScorePoints(scoredSeries, indexedResults ?? []),
            indexedResults,
            () => color,
            getYAxisId,
            isHidden
        )
    }, [scoredSeries, indexedResults, getYAxisId, isHidden])

    return markers.length > 0 ? <AnomalyPointsLayer markers={markers} radius={4} /> : null
}
