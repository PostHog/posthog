import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'VisionHog',
    scenes: {
        VisionHogScene: {
            import: () => import('./frontend/VisionHogScene'),
            name: 'VisionHog',
            projectBased: true,
            layout: 'app-container',
            activityScope: 'VisionHog',
        },
        VisionHogConfigScene: {
            import: () => import('./frontend/VisionHogConfigScene'),
            name: 'VisionHog Config',
            projectBased: true,
            layout: 'app-container',
            activityScope: 'VisionHog',
        },
        VisionHogVideoPlayerScene: {
            import: () => import('./frontend/VisionHogVideoPlayerScene'),
            name: 'VisionHog Video Player',
            projectBased: true,
            layout: 'app-container',
            activityScope: 'VisionHog',
        },
    },
    routes: {
        '/visionhog': ['VisionHogScene', 'visionHog'],
        '/visionhog/config': ['VisionHogConfigScene', 'visionHogConfig'],
        '/visionhog/camera/:id': ['VisionHogVideoPlayerScene', 'visionHogVideoPlayer'],
    },
    redirects: {},
    urls: {
        visionHog: (): string => '/visionhog',
        visionHogConfig: (): string => '/visionhog/config',
        visionHogVideoPlayer: (id: string): string => `/visionhog/camera/${id}`,
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
