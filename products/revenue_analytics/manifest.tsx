import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Revenue Analytics',
    scenes: {
        RevenueAnalytics: {
            name: 'Revenue Analytics',
            import: () => import('./frontend/RevenueAnalyticsScene'),
            projectBased: true,
            defaultDocsPath: '/docs/web-analytics/revenue-analytics',
            activityScope: 'RevenueAnalytics',
        },
    },
    routes: {
        '/revenue_analytics': ['RevenueAnalytics', 'revenueAnalytics'],
    },
    urls: {
        revenueAnalytics: (): string => '/revenue_analytics',
    },
    treeItemsProducts: [
        {
            path: 'Revenue analytics',
            category: 'Analytics',
            iconType: 'piggyBank',
            href: urls.revenueAnalytics(),
            tags: ['beta'],
            flag: FEATURE_FLAGS.REVENUE_ANALYTICS,
        },
    ],
    treeItemsMetadata: [
        {
            path: 'Revenue settings',
            category: 'Definitions',
            iconType: 'handMoney',
            href: urls.revenueSettings(),
            flag: FEATURE_FLAGS.REVENUE_ANALYTICS,
        },
    ],
}
