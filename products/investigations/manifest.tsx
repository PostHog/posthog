import { urls } from 'scenes/urls'

import { ProductItemCategory } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Investigations',
    urls: {
        investigations: (): string => '/investigations',
        investigation: (id: string): string => `/investigations/${encodeURIComponent(id)}`,
    },
    scenes: {
        Investigations: {
            name: 'Investigations',
            description: 'Investigate a question, test explanations, and share the evidence behind your decision.',
            import: () => import('./frontend/InvestigationsScene'),
            projectBased: true,
            iconType: 'investigation',
        },
        Investigation: {
            name: 'Investigation',
            import: () => import('./frontend/InvestigationScene'),
            projectBased: true,
            iconType: 'investigation',
        },
    },
    routes: {
        '/investigations': ['Investigations', 'investigations'],
        '/investigations/:id': ['Investigation', 'investigation'],
    },
    treeItemsProducts: [
        {
            path: 'Investigations',
            intents: [],
            href: urls.investigations(),
            category: ProductItemCategory.DATA,
            iconType: 'investigation',
            iconColor: ['var(--color-product-investigations-light)', 'var(--color-product-investigations-dark)'],
            searchKeywords: ['evidence', 'hypothesis', 'root cause', 'analysis'],
            tags: ['beta'],
            sceneKey: 'Investigations',
            sceneKeys: ['Investigations', 'Investigation'],
        },
    ],
}
