import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Metrics',
    scenes: {
        Metrics: {
            name: 'Metrics',
            import: () => import('./frontend/MetricsScene'),
            projectBased: true,
            layout: 'app-container',
            activityScope: 'Metrics',
            description: 'Monitor and analyze application metrics to understand system performance and health.',
            iconType: 'metrics',
            docsHref: 'https://posthog.com/docs/metrics',
        },
    },
    routes: {
        '/metrics': ['Metrics', 'metrics'],
    },
    redirects: {},
    urls: {
        metrics: (): string => '/metrics',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Metrics',
            intents: [ProductKey.METRICS],
            category: ProductItemCategory.APP_MONITORING,
            iconType: 'metrics',
            iconColor: [
                'var(--color-product-metrics-light)',
                'var(--color-product-metrics-dark)',
            ] as FileSystemIconColor,
            href: urls.metrics(),
            // Open alpha: the nav item is visible to everyone; the scene gate offers the
            // feature preview toggle to visitors who have not enrolled yet.
            tags: ['alpha'],
            sceneKey: 'Metrics',
        },
    ],
}
