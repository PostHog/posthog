import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Web Analytics',
    urls: {
        webAnalytics: (): string => `/web`,
        webAnalyticsWebVitals: (): string => `/web/web-vitals`,
        webAnalyticsPageReports: (): string => `/web/page-reports`,
        webAnalyticsMarketing: (): string => `/web/marketing`,
        webAnalyticsHealth: (): string => `/web/health`,
        webAnalyticsLive: (): string => `/web/live`,
        webAnalyticsBotAnalytics: (): string => `/web/bot-analytics`,
    },
    fileSystemTypes: {},
    treeItemsProducts: [
        {
            path: 'Web analytics',
            intents: [ProductKey.WEB_ANALYTICS],
            category: ProductItemCategory.ANALYTICS,
            iconType: 'web_analytics',
            iconColor: ['var(--color-product-web-analytics-light)'] as FileSystemIconColor,
            href: urls.webAnalytics(),
            sceneKey: 'WebAnalytics',
            sceneKeys: ['WebAnalytics'],
        },
    ],
    treeItemsMetadata: [],
}
