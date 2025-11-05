import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Revenue Analytics',
    scenes: {
        RevenueAnalytics: {
            name: 'Revenue Analytics',
            import: () => import('./frontend/RevenueAnalyticsScene'),
            projectBased: true,
            defaultDocsPath: '/docs/revenue-analytics',
            iconType: 'revenue_analytics',
            description: 'Track and analyze your revenue metrics to understand your business performance and growth.',
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
            href: urls.revenueAnalytics(),
            type: 'revenue',
            tags: ['beta'],
            sceneKey: 'RevenueAnalytics',
        },
    ],
    fileSystemTypes: {
        revenue: {
            name: 'Revenue',
            iconType: 'revenue_analytics' as FileSystemIconType,
            href: () => urls.revenueAnalytics(),
            iconColor: ['var(--color-product-revenue-analytics-light)', 'var(--color-product-revenue-analytics-dark)'],
            filterKey: 'revenue',
        },
    },
    treeItemsMetadata: [
        {
            path: 'Revenue definitions',
            category: 'Schema',
            iconType: 'revenue_analytics_metadata' as FileSystemIconType,
            href: urls.revenueSettings(),
            sceneKey: 'RevenueAnalytics',
        },
    ],
}
