import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Web Analytics',
    urls: {
        webAnalytics: (): string => `/web`,
        webAnalyticsWebVitals: (): string => `/web/web-vitals`,
        webAnalyticsPageReports: (): string => `/web/page-reports`,
        webAnalyticsMarketing: (): string => `/web/marketing`,
    },
    fileSystemTypes: {
        web_analytics: {
            name: 'Web analytics',
            iconType: 'web_analytics' as FileSystemIconType,
            href: () => urls.webAnalytics(),
            iconColor: ['var(--color-product-web-analytics-light)', 'var(--color-product-web-analytics-dark)'],
            filterKey: 'web_analytics',
        },
    },
    treeItemsProducts: [
        {
            path: 'Web analytics',
            category: 'Analytics',
            type: 'web_analytics',
            iconType: 'web_analytics',
            iconColor: ['var(--color-product-web-analytics-light)'] as FileSystemIconColor,
            href: urls.webAnalytics(),
        },
    ],
    treeItemsMetadata: [
        {
            path: 'Marketing settings',
            category: 'Definitions',
            iconType: 'marketing_settings' as FileSystemIconType,
            href: urls.marketingAnalytics(),
            flag: FEATURE_FLAGS.WEB_ANALYTICS_MARKETING,
        },
    ],
}
