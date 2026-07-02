import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { FileSystemIconColor, ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Pulse',
    scenes: {
        Pulse: {
            name: 'Pulse',
            import: () => import('./frontend/PulseScene'),
            projectBased: true,
            description: 'Recurring product briefs: what happened, why it happened, and what to build next.',
            iconType: 'activity',
        },
    },
    routes: {
        '/pulse': ['Pulse', 'pulse'],
    },
    redirects: {},
    urls: {
        pulse: (): string => '/pulse',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Pulse',
            intents: [ProductKey.PULSE],
            category: ProductItemCategory.UNRELEASED,
            iconType: 'activity',
            iconColor: [
                'var(--color-product-activity-light)',
                'var(--color-product-activity-dark)',
            ] as FileSystemIconColor,
            href: urls.pulse(),
            flag: FEATURE_FLAGS.PULSE,
            tags: ['alpha'],
            sceneKey: 'Pulse',
        },
    ],
}
