import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

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
        '/ml-inference/playground': ['DecisionPlayground', 'decisionPlayground'],
    },
    redirects: {
        '/ml-inference/decisions': (_params, searchParams, hashParams) =>
            combineUrl(urls.decisionPlayground(), searchParams, hashParams).url,
    },
    urls: {
        decisionPlayground: (): string => '/ml-inference/playground',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
