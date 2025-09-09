import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Embedded Analytics',
    urls: {
        embeddedAnalytics: (): string => `/embedded-analytics`,
    },
    fileSystemTypes: {
        embedded_analytics: {
            name: 'Embedded Analytics',
            iconType: 'embedded_analytics',
            href: () => urls.embeddedAnalytics(),
            iconColor: ['var(--color-product-embedded-analytics-light)'],
            filterKey: 'embedded_analytics',
            flag: FEATURE_FLAGS.EMBEDDED_ANALYTICS,
        },
    },
    treeItemsProducts: [
        {
            path: 'Embedded Analytics',
            category: 'Tools',
            href: urls.embeddedAnalytics(),
            type: 'embedded_analytics',
            flag: FEATURE_FLAGS.EMBEDDED_ANALYTICS,
            tags: ['alpha'],
            iconType: 'embedded_analytics',
            iconColor: ['var(--color-product-embedded-analytics-light)'] as FileSystemIconColor,
        },
    ],
}
