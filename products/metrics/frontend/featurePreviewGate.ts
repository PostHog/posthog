import { FEATURE_FLAGS } from 'lib/constants'

import { FeaturePreviewGateConfig } from '~/types'

export const metricsFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.METRICS,
    title: 'Metrics is in private alpha',
    description:
        'Metrics is available to select teams while we polish it. Metrics you send with an OpenTelemetry client are already stored, so ask us to turn on the viewer for your team, or read them with SQL now.',
    docsURL: 'https://posthog.com/docs/metrics',
    offerRequestAccess: true,
    storedDataQuery: `SELECT metric_name, count() AS samples, max(timestamp) AS last_seen
FROM posthog.metric_samples
WHERE timestamp > now() - INTERVAL 24 HOUR
GROUP BY metric_name
ORDER BY samples DESC`,
}
