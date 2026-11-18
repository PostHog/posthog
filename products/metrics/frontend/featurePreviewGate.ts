import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'
import { FeaturePreviewGateConfig } from '~/types'

export const metricsFeaturePreviewGate: FeaturePreviewGateConfig = {
    flag: FEATURE_FLAGS.METRICS,
    title: 'Metrics is in alpha',
    description:
        'Metrics is in open alpha: things may change while we polish it. Send metrics with any OpenTelemetry client, then turn on the feature preview to open the viewer.',
    docsURL: 'https://posthog.com/docs/metrics',
    sceneId: 'Metrics',
    productIntent: ProductKey.METRICS,
}
