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
            description:
                'Revenue events are used to track revenue in revenue analytics. You can choose which custom events PostHog should consider as revenue events, and which event property corresponds to the value of the event. You can also import revenue data from your PostHog data warehouse tables.',
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
            path: 'Revenue settings',
            category: 'Definitions',
            iconType: 'revenue_analytics_metadata' as FileSystemIconType,
            href: urls.revenueSettings(),
            sceneKey: 'RevenueAnalytics',
        },
    ],
}
