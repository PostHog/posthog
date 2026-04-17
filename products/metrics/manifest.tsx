import { FEATURE_FLAGS } from 'lib/constants'
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
            defaultDocsPath: '/docs/metrics',
            activityScope: 'Metrics',
            description: 'Monitor and analyze application metrics to understand system performance and health.',
            iconType: 'metrics',
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
            category: ProductItemCategory.UNRELEASED,
            iconType: 'metrics',
            iconColor: [
                'var(--color-product-metrics-light)',
                'var(--color-product-metrics-dark)',
            ] as FileSystemIconColor,
            href: urls.metrics(),
            flag: FEATURE_FLAGS.METRICS,
            tags: ['alpha'],
            sceneKey: 'Metrics',
        },
    ],
}
