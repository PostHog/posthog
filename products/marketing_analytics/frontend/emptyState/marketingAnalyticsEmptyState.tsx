import * as megaphonePng from '@posthog/brand/hoggies/png/megaphone'
import { IconMegaphone } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'

import { ProductKey } from '~/queries/schema/schema-general'

import { MarketingAnalyticsPreview } from './MarketingAnalyticsPreview'
import { marketingAnalyticsSetupLogic } from './marketingAnalyticsSetupLogic'

const HedgehogMegaphone = pngHoggie(megaphonePng)

export const marketingAnalyticsEmptyState: SceneProductEmptyState = {
    statusLogic: marketingAnalyticsSetupLogic,
    // The whole product is behind this flag; its in-scene banner handles the flag-off case.
    featureFlag: FEATURE_FLAGS.WEB_ANALYTICS_MARKETING,
    config: {
        productKey: ProductKey.MARKETING_ANALYTICS,
        productName: 'Marketing analytics',
        icon: <IconMegaphone />,
        accentColor: 'var(--color-product-marketing-analytics-light)',
        accentColorDark: 'var(--color-product-marketing-analytics-dark)',
        hedgehog: HedgehogMegaphone,
        text: {
            'needs-setup': {
                headline: 'See which ad spend actually converts',
                lead: 'Pull spend from Google Ads, Meta, LinkedIn, and your other ad platforms, join it with conversions you define, and compare cost per conversion and ROAS across channels and campaigns.',
            },
        },
        primaryAction: {
            label: 'Connect your ad platforms',
            onClick: () => {
                // The connect flow is the scene's own step-by-step setup, so
                // dismiss the gate and let it take over.
                productSetupStatusLogic
                    .findMounted({ productKey: ProductKey.MARKETING_ANALYTICS })
                    ?.actions.skipEmptyState()
            },
        },
        docsUrl: 'https://posthog.com/docs/web-analytics/marketing-analytics',
        previewLabel: 'Your channels, once connected',
        Preview: MarketingAnalyticsPreview,
    },
}
