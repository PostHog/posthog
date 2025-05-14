import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const visionHogProduct: ProductManifest = {
    name: 'VisionHog',
    scenes: {
        VisionHogScene: {
            import: () => import('./frontend/VisionHogScene'),
            name: 'VisionHog',
            projectBased: true,
            layout: 'app-container',
            activityScope: 'VisionHog',
        },
    },
    routes: {
        '/visionhog': ['VisionHogScene', 'visionHog'],
    },
    redirects: {},
    urls: {
        visionHog: (): string => '/visionhog',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'VisionHog',
            iconType: 'ai',
            href: urls.visionHog(),
        },
    ],
}

export default visionHogProduct
