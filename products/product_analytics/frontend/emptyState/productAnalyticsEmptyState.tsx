import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass-2'
import { IconGraph } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { ProductAnalyticsPreview } from './ProductAnalyticsPreview'
import { productAnalyticsSetupLogic } from './productAnalyticsSetupLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export const productAnalyticsEmptyState: SceneProductEmptyState = {
    statusLogic: productAnalyticsSetupLogic,
    config: {
        productKey: ProductKey.PRODUCT_ANALYTICS,
        productName: 'Product analytics',
        icon: <IconGraph />,
        accentColor: 'var(--color-product-product-analytics-light)',
        accentColorDark: 'var(--color-product-product-analytics-dark)',
        hedgehog: HedgehogMagnifyingGlass,
        text: {
            'needs-setup': {
                headline: 'Ask a question about your product and save the answer',
                lead: 'An insight is one question about the events you already send: how many people did this, where do they drop off, who comes back. Break the answer down by any property, then save it so you can reopen it later or drop it on a dashboard.',
            },
        },
        primaryAction: {
            label: 'Create your first insight',
            to: urls.insightNew(),
            dataAttr: 'add-insight-button-empty-state',
            accessControl: {
                resourceType: AccessControlResourceType.Insight,
                minAccessLevel: AccessControlLevel.Editor,
            },
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/product-analytics/insights',
        previewLabel: 'Your insights, once created',
        Preview: ProductAnalyticsPreview,
    },
}
