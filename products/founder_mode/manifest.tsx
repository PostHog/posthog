/**
 * Product manifest for founder_mode.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'FounderMode',
    scenes: {
        FounderMode: {
            name: 'Founder mode',
            import: () => import('./frontend/FounderMode'),
            projectBased: true,
            layout: 'plain',
        },
        FounderModeLayout: {
            name: 'Founder mode',
            import: () => import('./frontend/FounderModeLayout'),
            projectBased: true,
            layout: 'plain',
        },
    },
    routes: {
        '/init': ['FounderMode', 'founderMode'],
        '/founder': ['FounderModeLayout', 'founderModeLayout'],
    },
    redirects: {},
    urls: {
        founderMode: (): string => '/init',
        founderModeLayout: (): string => '/founder',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
