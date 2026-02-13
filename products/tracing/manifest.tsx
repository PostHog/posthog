import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Tracing',
    scenes: {
        Tracing: {
            import: () => import('./frontend/TracingScene'),
            projectBased: true,
            name: 'Tracing',
            activityScope: 'Tracing',
            layout: 'app-container',
            iconType: 'tracing',
            description: 'Monitor and analyze distributed traces across your services.',
            defaultDocsPath: '/docs/tracing',
        },
    },
    routes: {
        '/tracing': ['Tracing', 'tracing'],
    },
    redirects: {},
    urls: { tracing: (): string => '/tracing' },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Tracing',
            intents: [ProductKey.TRACING],
            category: 'Unreleased',
            iconType: 'tracing',
            iconColor: ['var(--color-product-logs-light)'] as FileSystemIconColor,
            href: urls.tracing(),
            sceneKey: 'Tracing',
            flag: FEATURE_FLAGS.TRACING,
            tags: ['alpha'],
        },
    ],
}
