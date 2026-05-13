/**
 * Product manifest for synthetic_tests.
 *
 * Defines scenes, routes, URLs, and navigation for the Synthetic tests product.
 */
import { combineUrl } from 'kea-router'

import { ProductItemCategory } from '../../frontend/src/queries/schema/schema-general'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Synthetic tests',
    scenes: {
        SyntheticTests: {
            import: () => import('./frontend/scenes/SyntheticTestsScene/SyntheticTestsScene'),
            projectBased: true,
            name: 'Synthetic tests',
            description: 'Scheduled browser checks against your product, seeded by session replays.',
        },
        SyntheticTest: {
            import: () => import('./frontend/scenes/SyntheticTestScene/SyntheticTestScene'),
            projectBased: true,
            name: 'Synthetic test',
        },
        SyntheticTestNew: {
            import: () => import('./frontend/scenes/SyntheticTestScene/SyntheticTestScene'),
            projectBased: true,
            name: 'New synthetic test',
        },
    },
    routes: {
        '/synthetic_tests': ['SyntheticTests', 'syntheticTests'],
        '/synthetic_tests/new': ['SyntheticTestNew', 'syntheticTestNew'],
        '/synthetic_tests/:id': ['SyntheticTest', 'syntheticTest'],
    },
    redirects: {},
    urls: {
        syntheticTests: (params: Record<string, string> = {}): string => combineUrl('/synthetic_tests', params).url,
        syntheticTestNew: (params: Record<string, string> = {}): string =>
            combineUrl('/synthetic_tests/new', params).url,
        syntheticTest: (id: string): string => `/synthetic_tests/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [
        {
            path: 'Synthetic test',
            type: 'synthetic_test',
            href: '/synthetic_tests/new',
        },
    ],
    treeItemsProducts: [
        {
            path: 'Synthetic tests',
            category: ProductItemCategory.BEHAVIOR,
            type: 'synthetic_tests',
            href: '/synthetic_tests',
            sceneKey: 'SyntheticTests',
        },
    ],
}
