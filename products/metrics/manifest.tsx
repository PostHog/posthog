import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
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
        MetricsDashboardReview: {
            name: 'Dashboard review',
            import: () => import('./frontend/dashboardReview/MetricsDashboardReviewScene'),
            projectBased: true,
            layout: 'app-container',
            activityScope: 'Metrics',
            description: 'Review AI-generated metrics dashboards before projects see them.',
            iconType: 'metrics',
        },
    },
    routes: {
        '/metrics': ['Metrics', 'metrics'],
        '/metrics/dashboard-review': ['MetricsDashboardReview', 'metricsDashboardReview'],
        '/metrics/dashboard-review/:templateId': ['MetricsDashboardReview', 'metricsDashboardReview'],
    },
    redirects: {},
    urls: {
        metrics: (activeTab?: MetricsSceneActiveTab): string =>
            activeTab ? `/metrics?activeTab=${activeTab}` : '/metrics',
        metricsDashboardReview: (templateId?: string): string =>
            templateId ? `/metrics/dashboard-review/${templateId}` : '/metrics/dashboard-review',
    },
    fileSystemTypes: {},
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
                { name: 'Viewer', href: urls.metrics('viewer') },
                { name: 'SQL', href: urls.metrics('sql') },
            ],
            // Open alpha: the nav item is visible to everyone; the scene gate offers the
            // feature preview toggle to visitors who have not enrolled yet.
            tags: ['alpha'],
            sceneKey: 'Metrics',
        },
    ],
}
