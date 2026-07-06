import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Tracing',
    scenes: {
        Tracing: {
            name: 'Tracing',
            import: () => import('./frontend/TracingScene'),
            projectBased: true,
            layout: 'app-container',
            activityScope: 'Tracing',
            description: 'Monitor and analyze distributed traces to understand service performance and debug issues.',
            iconType: 'tracing',
        },
        TracingOperation: {
            name: 'Operation',
            import: () => import('./frontend/TracingOperationScene'),
            projectBased: true,
            layout: 'app-container',
            activityScope: 'Tracing',
            description: 'Latency distribution and sample traces for a single operation.',
            iconType: 'tracing',
        },
    },
    routes: {
        '/tracing': ['Tracing', 'tracing'],
        '/tracing/operation': ['TracingOperation', 'tracingOperation'],
    },
    redirects: {},
    urls: {
        tracing: (): string => '/tracing',
        // Query params rather than path segments: span names ("GET /api/stats") contain slashes
        // and arbitrary characters that break path routing.
        tracingOperation: (serviceName: string, spanName: string): string =>
            combineUrl('/tracing/operation', { service: serviceName, name: spanName }).url,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Tracing',
            intents: [ProductKey.TRACING],
            category: ProductItemCategory.APP_MONITORING,
            iconType: 'tracing',
            iconColor: ['var(--color-product-tracing-light)'] as FileSystemIconColor,
            href: urls.tracing(),
            flag: FEATURE_FLAGS.TRACING,
            tags: ['alpha'],
            sceneKey: 'Tracing',
        },
    ],
}
