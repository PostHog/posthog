import { PRODUCT_VISUAL_ORDER } from 'lib/constants'
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
            iconType: 'piggyBank',
            href: urls.revenueAnalytics(),
            visualOrder: PRODUCT_VISUAL_ORDER.revenueAnalytics,
        },
    ],
    treeItemsDataManagement: [
        {
            path: 'Revenue settings',
            iconType: 'handMoney',
            href: urls.revenueSettings(),
        },
    ],
}
