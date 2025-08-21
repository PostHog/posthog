import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const WEB_ANALYTICS_PRODUCT_TREE_NAME = 'Web analytics'

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
            path: 'Web analytics', // Keep in sync with WEB_ANALYTICS_PRODUCT_TREE_NAME
            category: 'Analytics',
            iconType: 'pieChart',
            href: urls.webAnalytics(),
        },
    ],
}
