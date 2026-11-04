/**
 * Product manifest for warehouse_suggestions.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ActivityScope, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'WarehouseSuggestions',
    activityDescribers: {
        [ActivityScope.WAREHOUSE_SUGGESTION]: () =>
            import('./frontend/warehouseSuggestionActivityDescriber').then(
                (module) => module.warehouseSuggestionActivityDescriber
            ),
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
