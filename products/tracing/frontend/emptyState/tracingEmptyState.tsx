import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'
import { IconListTree } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import { setupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { SetupListeningIndicator } from 'lib/components/ProductEmptyState/SetupListeningIndicator'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { TRACING_DOCS_URL } from '../traceLinks'
import { TracingOtlpSetup } from './TracingOtlpSetup'
import { TracingPreview } from './TracingPreview'
import { tracingSetupDetection } from './tracingSetupDetection'

const HedgehogXRay = pngHoggie(xRayPng)

export const tracingEmptyState: SceneProductEmptyState = {
    detection: tracingSetupDetection,
    config: {
        productKey: ProductKey.TRACING,
        productName: 'Tracing',
        icon: <IconListTree />,
        accentColor: 'var(--color-product-tracing-light)',
        accentColorDark: 'var(--color-product-tracing-dark)',
        hedgehog: HedgehogXRay,
        text: {
            'needs-setup': {
                headline: 'See where every request spends its time',
                lead: 'Send spans from the PostHog Node.js or Python SDK, or from any OpenTelemetry-compatible client over OTLP. Follow a request across services, find the span that slows it down, and watch latency over time.',
            },
        },
        PrimaryAction: TracingOtlpSetup,
        docsUrl: TRACING_DOCS_URL,
        statusIndicator: (
            <SetupListeningIndicator
                productKey={ProductKey.TRACING}
                statusLogic={setupDetectionLogic(tracingSetupDetection)}
                dataName="span"
                destination={{ label: 'Go to Tracing', url: urls.tracing() }}
            />
        ),
        previewLabel: 'Your traces, once connected',
        Preview: TracingPreview,
    },
}
