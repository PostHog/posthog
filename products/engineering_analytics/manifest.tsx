/**
 * Product manifest for engineering_analytics.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'EngineeringAnalytics',
    scenes: {
        EngineeringAnalytics: {
            import: () => import('./frontend/scenes/EngineeringAnalyticsScene'),
            projectBased: true,
            name: 'CI analytics',
            layout: 'app-container',
            description: 'Open PRs are the unit of work — track CI health, throughput, and where engineering hours go.',
            iconType: 'metrics',
        },
    },
    routes: {
        '/engineering-analytics': ['EngineeringAnalytics', 'engineeringAnalytics'],
        '/engineering-analytics/workflows': ['EngineeringAnalytics', 'engineeringAnalyticsWorkflows'],
    },
    redirects: {},
    urls: {
        engineeringAnalytics: (): string => '/engineering-analytics',
        engineeringAnalyticsWorkflows: (): string => '/engineering-analytics/workflows',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'CI analytics',
            intents: [ProductKey.ENGINEERING_ANALYTICS],
            category: ProductItemCategory.UNRELEASED,
            type: 'engineering_analytics',
            iconType: 'metrics' as FileSystemIconType,
            iconColor: ['var(--color-product-data-warehouse-light)'] as FileSystemIconColor,
            href: urls.engineeringAnalytics(),
            flag: FEATURE_FLAGS.ENGINEERING_ANALYTICS,
            tags: ['beta'],
            sceneKey: 'EngineeringAnalytics',
        },
    ],
}
