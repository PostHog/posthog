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
    },
    routes: {
        '/githog': ['GitHog', 'gitHog'],
    },
    redirects: {},
    urls: {
        gitHog: (): string => '/githog',
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
