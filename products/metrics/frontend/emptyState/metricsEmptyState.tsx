import * as chartPng from '@posthog/brand/hoggies/png/chart'
import { IconGraph } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { MetricsPreview } from './MetricsPreview'
import { MetricsScrapeAgentSetup } from './MetricsScrapeAgentSetup'
import { metricsSetupLogic } from './metricsSetupLogic'

const HedgehogChart = pngHoggie(chartPng)

export const metricsEmptyState: SceneProductEmptyState = {
    statusLogic: metricsSetupLogic,
    // The whole product is behind this flag; its feature-preview gate handles the flag-off case.
    featureFlag: FEATURE_FLAGS.METRICS,
    config: {
        productKey: ProductKey.METRICS,
        productName: 'Metrics',
        icon: <IconGraph />,
        accentColor: 'var(--color-product-metrics-light)',
        accentColorDark: 'var(--color-product-metrics-dark)',
        hedgehog: HedgehogChart,
        text: {
            'needs-setup': {
                headline: 'Watch your counters, gauges, and histograms live',
                lead: 'Send metrics from the PostHog SDK you already have, from any OpenTelemetry-compatible client over OTLP, or by scraping the Prometheus endpoints you already expose. Chart them next to your product data and query them with SQL.',
                hint: 'Starting fresh? Wizard wires up metrics in your app:',
            },
        },
        wizard: { slug: 'metrics', pinProjectId: true },
        PrimaryAction: MetricsScrapeAgentSetup,
        docsUrl: 'https://posthog.com/docs/metrics',
        previewLabel: 'Your metrics, once connected',
        Preview: MetricsPreview,
    },
}
