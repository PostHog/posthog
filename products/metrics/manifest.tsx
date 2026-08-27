import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
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
        },
        MetricsPipelines: {
            name: 'Pipelines',
            import: () => import('./frontend/pipelines/PipelinesScene'),
            projectBased: true,
            activityScope: 'MetricsPipeline',
            description: 'Live topology of your systems: nodes with health stats, edges with throughput vs baseline.',
            iconType: 'metrics',
        },
        MetricsPipeline: {
            name: 'Pipeline',
            import: () => import('./frontend/pipelines/PipelineScene'),
            projectBased: true,
            activityScope: 'MetricsPipeline',
            iconType: 'metrics',
        },
    },
    routes: {
        '/metrics': ['Metrics', 'metrics'],
        '/metrics/pipelines': ['MetricsPipelines', 'metricsPipelines'],
        '/metrics/pipelines/:id': ['MetricsPipeline', 'metricsPipeline'],
    },
    redirects: {},
    urls: {
        metrics: (): string => '/metrics',
        metricsPipelines: (): string => '/metrics/pipelines',
        metricsPipeline:
            /** @param id A UUID or 'new'. ':id' for routing. */
            (id: string): string => `/metrics/pipelines/${id}`,
    },
    fileSystemTypes: {
        metrics_pipeline: {
            name: 'Pipeline (metrics)',
            iconType: 'metrics' as FileSystemIconType,
            href: (ref: string) => urls.metricsPipeline(ref),
            iconColor: [
                'var(--color-product-metrics-light)',
                'var(--color-product-metrics-dark)',
            ] as FileSystemIconColor,
            filterKey: 'metrics_pipeline',
            flag: FEATURE_FLAGS.METRICS_PIPELINES,
        },
    },
    treeItemsNew: [
        {
            path: 'Pipeline (metrics)',
            type: 'metrics_pipeline',
            href: urls.metricsPipeline('new'),
            iconType: 'metrics' as FileSystemIconType,
            iconColor: [
                'var(--color-product-metrics-light)',
                'var(--color-product-metrics-dark)',
            ] as FileSystemIconColor,
            flag: FEATURE_FLAGS.METRICS_PIPELINES,
        },
    ],
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
            flag: FEATURE_FLAGS.METRICS,
            tags: ['alpha'],
            sceneKey: 'Metrics',
        },
    ],
}
