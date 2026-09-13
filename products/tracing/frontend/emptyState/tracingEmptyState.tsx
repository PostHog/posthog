import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'
import { IconListTree } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { TracingPreview } from './TracingPreview'
import { tracingSetupLogic } from './tracingSetupLogic'

const HedgehogXRay = pngHoggie(xRayPng)

export const tracingEmptyState: SceneProductEmptyState = {
    statusLogic: tracingSetupLogic,
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
                lead: 'Send spans from any OpenTelemetry-compatible client over OTLP. No PostHog-specific packages needed. Follow a request across services, find the span that slows it down, and watch latency over time.',
            },
        },
        docsUrl: 'https://posthog.com/docs/tracing',
        previewLabel: 'Your traces, once connected',
        Preview: TracingPreview,
    },
}
