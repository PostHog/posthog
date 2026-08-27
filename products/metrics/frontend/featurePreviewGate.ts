import { FEATURE_FLAGS } from 'lib/constants'

import { FeaturePreviewGateConfig } from '~/types'

export const metricsFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.METRICS,
    title: 'Metrics is in private alpha',
    description:
        "Metrics is available to select teams while we polish it. You can already send metrics with any OpenTelemetry client. Join the waitlist and we'll turn on the viewer for your team.",
    docsURL: 'https://posthog.com/docs/metrics',
}

// Pipelines rolls out on its own flag inside the metrics alpha, so the scenes
// gate separately. Without this the routes still render for a team that only
// has `metrics`, and the list just fails against a 403.
export const pipelinesFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.METRICS_PIPELINES,
    title: 'Pipelines is in private alpha',
    description:
        'Pipelines maps your components onto the metrics you already send, and colors each one by thresholds you set. It is going out to a few teams at a time while we shape it.',
    docsURL: 'https://posthog.com/docs/metrics',
}
