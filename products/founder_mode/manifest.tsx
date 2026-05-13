/**
 * Product manifest for founder_mode.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'FounderMode',
    scenes: {
        Founders: {
            name: 'Founders',
            import: () => import('./frontend/scenes/FoundersScene'),
            projectBased: true,
            layout: 'app-container',
        },
    },
    routes: {
        '/founder': ['Founders', 'founders'],
    },
    redirects: {},
    urls: {
        founders: (): string => '/founder',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
