/**
 * Product manifest for githog.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductItemCategory, ProductKey } from '../../frontend/src/queries/schema/schema-general'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Githog',
    scenes: {
        GitHog: {
            name: 'GitHog',
            projectBased: true,
            import: () => import('./frontend/scenes/GitHogScene'),
            iconType: 'default_icon_type',
        },
        GitHogPRReview: {
            name: 'PR review',
            projectBased: true,
            import: () => import('./frontend/scenes/GitHogPRReviewScene'),
        },
    },
    routes: {
        '/githog': ['GitHog', 'gitHog'],
        '/githog/pr/:id': ['GitHogPRReview', 'gitHogPRReview'],
    },
    redirects: {},
    urls: {
        gitHog: (): string => '/githog',
        gitHogPRReview: (id: string): string => `/githog/pr/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'GitHog',
            intents: [ProductKey.GITHOG],
            category: ProductItemCategory.UNRELEASED,
            href: '/githog',
            iconType: 'default_icon_type',
            sceneKey: 'GitHog',
        },
    ],
}
