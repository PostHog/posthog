/**
 * Product manifest for orchestra.
 *
 * Defines scenes, routes, URLs, and navigation for this product.
 */
import { ProductItemCategory, ProductKey } from '../../frontend/src/queries/schema/schema-general'
import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Orchestra',
    scenes: {
        Orchestra: {
            name: 'Orchestra',
            projectBased: true,
            iconType: 'orchestra',
            import: () => import('./frontend/scenes/OrchestraScene'),
        },
        OrchestraExecution: {
            name: 'Orchestra execution',
            projectBased: true,
            iconType: 'orchestra',
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
    treeItemsProducts: [
        {
            path: 'Orchestra',
            intents: [ProductKey.WORKFLOWS],
            category: ProductItemCategory.TOOLS,
            iconType: 'orchestra',
            iconColor: ['var(--color-product-surveys-light)'],
            href: '/orchestra',
            sceneKey: 'Orchestra',
            sceneKeys: ['Orchestra', 'OrchestraExecution'],
        },
    ],
}
