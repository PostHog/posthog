import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Embedded Analytics',
    scenes: {
        EmbeddedAnalytics: {
            import: () => import('./frontend/EmbeddedAnalyticsScene'),
            projectBased: true,
            name: 'Embedded analytics',
            activityScope: 'EmbeddedAnalytics',
            layout: 'app-container',
            defaultDocsPath: '/docs/embedded-analytics',
        },
        EmbeddedAnalyticsUsage: {
            import: () => import('./frontend/Usage'),
            projectBased: true,
            name: 'Embedded analytics usage',
            activityScope: 'EmbeddedAnalytics',
            layout: 'app-container',
        },
        EmbeddedAnalyticsQueryEndpoints: {
            import: () => import('./frontend/QueryEndpoints'),
            projectBased: true,
            name: 'Embedded analytics query endpoints',
            activityScope: 'EmbeddedAnalytics',
            layout: 'app-container',
        },
    },
    routes: {
        '/embedded-analytics': ['EmbeddedAnalytics', 'embeddedAnalytics'],
        // EmbeddedAnalytics stays first as scene for Usage!
        '/embedded-analytics/usage': ['EmbeddedAnalytics', 'embeddedAnalyticsUsage'],
        '/embedded-analytics/query-endpoints': ['EmbeddedAnalytics', 'embeddedAnalyticsQueryEndpoints'],
    },
    urls: {
        embeddedAnalytics: (): string => '/embedded-analytics',
        embeddedAnalyticsUsage: (params?: {
            dateFrom?: string
            dateTo?: string
            requestNameBreakdownEnabled?: string
            requestNameFilter?: string[]
        }): string => {
            const queryParams = new URLSearchParams(params as Record<string, string>)
            const stringifiedParams = queryParams.toString()
            return `/embedded-analytics/usage${stringifiedParams ? `?${stringifiedParams}` : ''}`
        },
        embeddedAnalyticsQueryEndpoints: (): string => '/embedded-analytics/query-endpoints',
    },
    fileSystemTypes: {
        embedded_analytics: {
            name: 'Embedded analytics',
            iconType: 'embedded_analytics',
            href: () => urls.embeddedAnalyticsQueryEndpoints(),
            iconColor: ['var(--color-product-embedded-analytics-light)'],
            filterKey: 'embedded_analytics',
            flag: FEATURE_FLAGS.EMBEDDED_ANALYTICS,
        },
    },
    treeItemsProducts: [
        {
            path: 'Embedded analytics',
            category: 'Unreleased',
            href: urls.embeddedAnalyticsQueryEndpoints(),
            type: 'embedded_analytics',
            flag: FEATURE_FLAGS.EMBEDDED_ANALYTICS,
            tags: ['alpha'],
            iconType: 'embedded_analytics',
            iconColor: ['var(--color-product-embedded-analytics-light)'] as FileSystemIconColor,
        },
    ],
    treeItemsMetadata: [
        {
            path: 'Embedded analytics',
            category: 'Unreleased',
            iconType: 'embedded_analytics' as FileSystemIconType,
            iconColor: ['var(--color-product-embedded-analytics-light)'] as FileSystemIconColor,
            href: urls.embeddedAnalyticsQueryEndpoints(),
        },
    ],
}
