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
        FounderModeBlank: {
            name: 'Founder mode',
            import: () => import('./frontend/FounderModeBlank'),
            projectBased: true,
            layout: 'plain',
        },
    },
    routes: {
        '/init': ['FounderMode', 'founderMode'],
        '/init/founder': ['FounderModeBlank', 'founderModeBlank'],
    },
    redirects: {},
    urls: {
        founderMode: (): string => '/init',
        founderModeBlank: (): string => '/init/founder',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
