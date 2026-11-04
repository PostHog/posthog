/**
 * Product manifest for exports.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ActivityScope, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Exports',
    activityDescribers: {
        [ActivityScope.EXPORTED_ASSET]: () =>
            import('scenes/exports/activityDescriptions').then((module) => module.exportedAssetActivityDescriber),
    },
    scenes: {
        // Define scenes here
    },
    routes: {
        // Define routes here
    },
    redirects: {},
    urls: {
        // Define URL helpers here
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
