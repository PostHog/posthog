import { FEATURE_FLAGS, INSIGHT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { MetricsQuery, NodeKind, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

import type { MetricsSceneActiveTab } from './frontend/metricsSceneLogic'

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
        metrics: (activeTab?: MetricsSceneActiveTab): string =>
            activeTab ? `/metrics?activeTab=${activeTab}` : '/metrics',
    },
    fileSystemTypes: {},
    treeItemsNew: [
        {
            path: `Insight/Metrics`,
            type: 'insight',
            href: urls.insightNew({
                query: { kind: NodeKind.MetricsQuery, clauses: [], dateRange: { date_from: '-1h' } } as MetricsQuery,
            }),
            flag: FEATURE_FLAGS.METRICS_INSIGHT_BUILDER,
            iconType: 'metrics',
            visualOrder: INSIGHT_VISUAL_ORDER.metrics,
            sceneKeys: ['Insight'],
        },
    ],
    treeItemsProducts: [
        {
            path: 'Metrics',
            intents: [ProductKey.METRICS],
            category: ProductItemCategory.MONITORING,
            iconType: 'metrics',
            iconColor: [
                'var(--color-product-metrics-light)',
                'var(--color-product-metrics-dark)',
            ] as FileSystemIconColor,
            href: urls.metrics(),
            searchKeywords: ['time series', 'counters', 'gauges'],
            searchTabs: [
                { name: 'Explore', href: urls.metrics('explore') },
                { name: 'SQL', href: urls.metrics('sql') },
            ],
            // Open alpha: the nav item is visible to everyone; the scene gate offers the
            // feature preview toggle to visitors who have not enrolled yet.
            tags: ['alpha'],
            sceneKey: 'Metrics',
        },
    ],
}
