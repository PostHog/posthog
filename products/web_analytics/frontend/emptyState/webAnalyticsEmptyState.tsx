import * as explorerPng from '@posthog/brand/hoggies/png/explorer'
import { IconPieChart } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { WebAnalyticsPreview } from './WebAnalyticsPreview'
import { webAnalyticsSetupLogic } from './webAnalyticsSetupLogic'

const HedgehogExplorer = pngHoggie(explorerPng)

/**
 * The web analytics setup screen. The web analytics scene shows its own dashboard from the first
 * pageview, so no scene gate uses this: the onboarding welcome page renders it for projects that
 * have not sent a pageview yet.
 */
export const webAnalyticsEmptyState: SceneProductEmptyState = {
    statusLogic: webAnalyticsSetupLogic,
    config: {
        productKey: ProductKey.WEB_ANALYTICS,
        productName: 'Web analytics',
        icon: <IconPieChart />,
        accentColor: 'var(--color-product-web-analytics-light)',
        accentColorDark: 'var(--color-product-web-analytics-dark)',
        hedgehog: HedgehogExplorer,
        text: {
            'needs-setup': {
                headline: 'See where your visitors come from',
                lead: 'Visitors, top pages, channels, and bounce rate on one dashboard. It fills in from the pageviews posthog-js captures, so once PostHog is installed there is nothing else to configure.',
            },
        },
        primaryAction: {
            label: 'Open web analytics',
            to: urls.webAnalytics(),
            dataAttr: 'web-analytics-empty-state-open',
        },
        docsUrl: 'https://posthog.com/docs/web-analytics/getting-started',
        previewLabel: 'Example: your traffic, once pageviews arrive',
        Preview: WebAnalyticsPreview,
        skippable: false,
    },
}
