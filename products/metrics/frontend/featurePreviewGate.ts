import { FEATURE_FLAGS } from 'lib/constants'

import { FeaturePreviewGateConfig } from '~/types'

export const metricsFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.METRICS,
    title: 'Metrics is in private alpha',
    description:
        "Metrics is available to select teams while we polish it. You can already send metrics with any OpenTelemetry client. Join the waitlist and we'll turn on the viewer for your team.",
    docsURL: 'https://posthog.com/docs/metrics',
}
