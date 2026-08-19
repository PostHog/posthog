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
        StamphogRuns: {
            import: () => import('./frontend/scenes/StamphogRunsScene/StamphogRunsScene'),
            projectBased: true,
            name: 'Stamphog runs',
            iconType: 'stamphog',
        },
        StamphogDigests: {
            import: () => import('./frontend/scenes/StamphogDigestsScene/StamphogDigestsScene'),
            projectBased: true,
            name: 'Stamphog digests',
            iconType: 'stamphog',
        },
    },
    routes: {
        '/stamphog': ['Stamphog', 'stamphog'],
        '/stamphog/runs': ['StamphogRuns', 'stamphogRuns'],
        '/stamphog/digests': ['StamphogDigests', 'stamphogDigests'],
        // GitHub App Setup URL — GitHub redirects here after install with an installation_id search
        // param. Lives under the product's own /stamphog namespace, not /integrations/*, so the generic
        // /integrations/:kind/callback scene route can't shadow it (product routes register after core).
        '/stamphog/install/callback': ['Stamphog', 'stamphogCallback'],
    },
    redirects: {},
    urls: {
        stamphog: (): string => '/stamphog',
        stamphogRuns: (): string => '/stamphog/runs',
        stamphogDigests: (): string => '/stamphog/digests',
        stamphogCallback: (): string => '/stamphog/install/callback',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
