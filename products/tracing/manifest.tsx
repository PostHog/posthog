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
            defaultDocsPath: '/docs/tracing',
            activityScope: 'Tracing',
            description: 'Monitor and analyze distributed traces to understand service performance and debug issues.',
            iconType: 'tracing',
        },
    },
    routes: {
        '/tracing': ['Tracing', 'tracing'],
    },
    redirects: {},
    urls: {
        tracing: (): string => '/tracing',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Tracing',
            intents: [ProductKey.TRACING],
            category: ProductItemCategory.UNRELEASED,
            iconType: 'tracing',
            iconColor: ['var(--color-product-tracing-light)'] as FileSystemIconColor,
            href: urls.tracing(),
            flag: FEATURE_FLAGS.TRACING,
            tags: ['alpha'],
            sceneKey: 'Tracing',
        },
    ],
}
