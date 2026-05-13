/**
 * Product manifest for orchestra.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Orchestra',
    scenes: {
        Orchestra: {
            name: 'Orchestra',
            projectBased: true,
            import: () => import('./frontend/scenes/OrchestraScene'),
        },
        OrchestraExecution: {
            name: 'Orchestra execution',
            projectBased: true,
            import: () => import('./frontend/scenes/OrchestraExecutionScene'),
        },
    },
    routes: {
        '/orchestra': ['Orchestra', 'orchestra'],
        '/orchestra/executions/:id': ['OrchestraExecution', 'orchestraExecution'],
    },
    redirects: {},
    urls: {
        orchestra: (): string => '/orchestra',
        orchestraExecution: (id: string): string => `/orchestra/executions/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
