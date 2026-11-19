import { useValues } from 'kea'
import { router } from 'kea-router'
import { Suspense } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { ANOMALY_SCORES_SEARCH_PARAM } from './anomalyScoresParam'
import type { TrendsAnomalyScoreOverlayProps } from './TrendsAnomalyScoreOverlay'

// Only a link from the Anomalies tab asks for the marks, so their code and request stay out of every other chart.
const TrendsAnomalyScoreOverlay = lazyWithRetry(() =>
    import('./TrendsAnomalyScoreOverlay').then((module) => ({ default: module.TrendsAnomalyScoreOverlay }))
)

/** The anomaly score marks, for a chart that was opened from the Anomalies tab. Renders nothing otherwise. */
export function RequestedAnomalyScoreOverlay(props: TrendsAnomalyScoreOverlayProps): JSX.Element | null {
    const enabled = useFeatureFlag('ANOMALIES_TAB')
    const { searchParams } = useValues(router)

    if (!enabled || !searchParams[ANOMALY_SCORES_SEARCH_PARAM]) {
        return null
    }
    return (
        <Suspense fallback={null}>
            <TrendsAnomalyScoreOverlay {...props} />
        </Suspense>
    )
}
