/**
 * Product manifest for githog.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductItemCategory, ProductKey } from '../../frontend/src/queries/schema/schema-general'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'GitHog',
    scenes: {
        GitHog: {
            name: 'GitHog',
            projectBased: true,
            import: () => import('./frontend/scenes/GitHogScene'),
            iconType: 'default_icon_type',
        },
        GitHogRepo: {
            name: 'GitHog repo',
            projectBased: true,
            import: () => import('./frontend/scenes/GitHogRepoScene'),
            iconType: 'default_icon_type',
        },
    },
    routes: {
        '/githog': ['GitHog', 'gitHog'],
        '/githog/repos/:owner/:name': ['GitHogRepo', 'gitHogRepo'],
        // Same scene as the repo inbox — the :number param drives which PR is
        // selected in the right-hand workspace.
        '/githog/repos/:owner/:name/pulls/:number': ['GitHogRepo', 'gitHogPullRequest'],
    },
    redirects: {},
    urls: {
        gitHog: (): string => '/githog',
        gitHogRepo: (owner: string, name: string): string =>
            `/githog/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`,
        gitHogPullRequest: (owner: string, name: string, number: number | string): string =>
            `/githog/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/pulls/${number}`,
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
