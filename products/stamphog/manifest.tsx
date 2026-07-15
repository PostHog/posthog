/**
 * Product manifest for stamphog.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Stamphog',
    scenes: {
        Stamphog: {
            // Single scene handles both the landing/list view and the post-install
            // GitHub App callback — the scene logic inspects search params to decide.
            import: () => import('./frontend/scenes/StamphogScene/StamphogScene'),
            projectBased: true,
            name: 'Stamphog',
            iconType: 'stamphog',
        },
    },
    routes: {
        '/stamphog': ['Stamphog', 'stamphog'],
        // GitHub App Setup URL — GitHub redirects here after install with an installation_id search
        // param. Lives under the product's own /stamphog namespace, not /integrations/*, so the generic
        // /integrations/:kind/callback scene route can't shadow it (product routes register after core).
        '/stamphog/install/callback': ['Stamphog', 'stamphogCallback'],
    },
    redirects: {},
    urls: {
        stamphog: (): string => '/stamphog',
        stamphogCallback: (): string => '/stamphog/install/callback',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
