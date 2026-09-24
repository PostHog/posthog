import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'MlInference',
    scenes: {
        DecisionPlayground: {
            import: () => import('./frontend/DecisionPlaygroundScene'),
            projectBased: true,
            name: 'Decisions playground',
            description: 'Ask the decision model questions about a piece of text.',
            layout: 'app-container',
        },
    },
    routes: {
        '/ml-inference/decisions': ['DecisionPlayground', 'decisionPlayground'],
    },
    redirects: {},
    urls: {
        decisionPlayground: (): string => '/ml-inference/decisions',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
