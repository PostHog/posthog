import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Marketing Analytics',
    urls: {
        marketingAnalyticsApp: (): string => '/marketing',
    },
    fileSystemTypes: {},
    treeItemsProducts: [
        {
            path: 'Marketing analytics',
            intents: [ProductKey.MARKETING_ANALYTICS],
            category: 'Analytics',
            href: urls.marketingAnalyticsApp(),
            iconType: 'marketing_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-marketing-analytics-light)'] as FileSystemIconColor,
            tags: ['beta'],
            flag: FEATURE_FLAGS.WEB_ANALYTICS_MARKETING,
            sceneKey: 'MarketingAnalytics',
            sceneKeys: ['MarketingAnalytics'],
        },
    ],
    treeItemsMetadata: [],
}
