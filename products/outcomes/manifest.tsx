import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Outcomes',
    scenes: {
        Outcomes: {
            name: 'Outcomes',
            import: () => import('./frontend/OutcomesScene'),
            projectBased: true,
            description:
                'Define conditions over events that, once met by a person, become permanent facts and emit an event.',
            iconType: 'metrics',
        },
        Outcome: {
            name: 'Outcome',
            import: () => import('./frontend/OutcomeScene'),
            projectBased: true,
            iconType: 'metrics',
        },
    },
    routes: {
        '/outcomes': ['Outcomes', 'outcomes'],
        '/outcomes/:id': ['Outcome', 'outcome'],
    },
    urls: {
        outcomes: (): string => '/outcomes',
        outcome: (id: string): string => `/outcomes/${id}`,
    },
    treeItemsProducts: [
        {
            path: 'Outcomes',
            intents: [ProductKey.OUTCOMES],
            category: ProductItemCategory.UNRELEASED,
            iconType: 'metrics',
            href: urls.outcomes(),
            flag: FEATURE_FLAGS.OUTCOMES,
            tags: ['alpha'],
            sceneKey: 'Outcomes',
        },
    ],
}
