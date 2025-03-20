import { IconPieChart } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Web Analytics',
    urls: {
        webAnalytics: (): string => `/web`,
        webAnalyticsWebVitals: (): string => `/web/web-vitals`,
        webAnalyticsPageReports: (): string => `/web/page-reports`,
    },
    fileSystemTypes: {},
    treeItems: [
        {
            path: 'Explore/Web Analytics',
            icon: <IconPieChart />,
            href: () => urls.webAnalytics(),
        },
    ],
}
