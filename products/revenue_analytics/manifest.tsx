import { IconRocket } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Revenue Analytics',
    scenes: {
        RevenueAnalytics: {
            name: 'Revenue Analytics',
            import: () => import('./frontend/RevenueAnalyticsDashboard'),
            projectBased: true,
            defaultDocsPath: '/docs/revenue-analytics',
            activityScope: 'RevenueAnalytics',
        },
    },
    routes: {
        '/revenue_analytics': ['RevenueAnalytics', 'revenueAnalytics'],
    },
    redirects: {},
    urls: {
        revenueAnalytics: (): string => '/revenue_analytics',
    },
    fileSystemTypes: {
        // TODO: add to project tree backend
        // revenue_analytics: {
        //     icon: <IconRocket />,
        //     href: (ref: string) => urls.revenueAnalytics(ref),
        // },
    },
    treeItems: [
        {
            path: 'Explore/Revenue analytics',
            icon: <IconRocket />,
            href: () => urls.revenueAnalytics(),
        },
    ],
}
