/**
 * Product manifest for foundry.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Foundry',
    scenes: {
        Foundry: {
            name: 'Foundry',
            import: () => import('./frontend/FoundryScene'),
            projectBased: true,
            description: 'A portfolio of bets: hypotheses shipped behind flags and verified by the market.',
            iconType: 'experiment',
        },
        FoundryBet: {
            name: 'Bet',
            import: () => import('./frontend/FoundryBetScene'),
            projectBased: true,
        },
    },
    routes: {
        '/foundry': ['Foundry', 'foundry'],
        '/foundry/:id': ['FoundryBet', 'foundryBet'],
    },
    redirects: {},
    urls: {
        foundry: (): string => '/foundry',
        foundryBet: (id: string): string => `/foundry/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Foundry',
            intents: [ProductKey.FOUNDRY],
            category: ProductItemCategory.UNRELEASED,
            href: urls.foundry(),
            tags: ['alpha'],
            iconType: 'experiment',
            sceneKey: 'Foundry',
        },
    ],
}
