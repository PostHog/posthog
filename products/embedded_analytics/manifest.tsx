import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { EmbeddedTab } from 'scenes/embedded-analytics/common'
import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Embedded analytics',
    urls: {
        embeddedAnalytics: (tab: EmbeddedTab | ':tab' = EmbeddedTab.QUERY_ENDPOINTS, params = {}): string =>
            combineUrl(`/embedded-analytics/${tab}`, params).url,
    },
    fileSystemTypes: {
        embedded_analytics: {
            name: 'Embedded analytics',
            iconType: 'embedded_analytics',
            href: () => urls.embeddedAnalytics(EmbeddedTab.QUERY_ENDPOINTS),
            iconColor: ['var(--color-product-embedded-analytics-light)'],
            filterKey: 'embedded_analytics',
            flag: FEATURE_FLAGS.EMBEDDED_ANALYTICS,
        },
    },
    treeItemsProducts: [
        {
            path: 'Embedded analytics',
            category: 'Unreleased',
            href: urls.embeddedAnalytics(EmbeddedTab.QUERY_ENDPOINTS),
            type: 'embedded_analytics',
            flag: FEATURE_FLAGS.EMBEDDED_ANALYTICS,
            tags: ['alpha'],
            iconType: 'embedded_analytics',
            iconColor: ['var(--color-product-embedded-analytics-light)'] as FileSystemIconColor,
        },
    ],
}
