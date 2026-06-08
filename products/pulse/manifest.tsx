import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Pulse',
    scenes: {
        Pulse: {
            name: 'Pulse',
            import: () => import('./frontend/Pulse'),
            projectBased: true,
            description: "Proactive insights surfaced by Max from your team's key metrics.",
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
            intents: [ProductKey.MAX],
            category: ProductItemCategory.ANALYTICS,
            iconType: 'activity',
            href: urls.pulse(),
            flag: FEATURE_FLAGS.MAX_PULSE,
            tags: ['beta'],
            sceneKey: 'Pulse',
            sceneKeys: ['Pulse'],
        },
    ],
}
