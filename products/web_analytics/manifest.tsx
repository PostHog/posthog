import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Web Analytics',
    urls: {
        webAnalytics: (): string => `/web`,
        webAnalyticsWebVitals: (): string => `/web/web-vitals`,
        webAnalyticsPageReports: (): string => `/web/page-reports`,
        webAnalyticsMarketing: (): string => `/web/marketing`,
    },
    fileSystemTypes: {},
    treeItemsProducts: [
        {
            path: 'Web analytics',
            category: 'Analytics',
            iconType: 'web_analytics',
            iconColor: ['var(--color-product-web-analytics-light)'] as FileSystemIconColor,
            href: urls.webAnalytics(),
        },
    ],
}
