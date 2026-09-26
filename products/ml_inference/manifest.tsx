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
        MagicEightBall: {
            import: () => import('./frontend/MagicEightBallScene'),
            projectBased: true,
            name: 'Magic 8 ball',
            description: 'Ask a product question and let the decision model shake out an answer.',
            layout: 'app-container',
        },
    },
    routes: {
        '/ml-inference/playground': ['DecisionPlayground', 'decisionPlayground'],
        '/ml-inference/magic-8-ball': ['MagicEightBall', 'magicEightBall'],
    },
    redirects: {
        '/ml-inference/decisions': '/ml-inference/playground',
    },
    urls: {
        decisionPlayground: (): string => '/ml-inference/playground',
        magicEightBall: (): string => '/ml-inference/magic-8-ball',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
