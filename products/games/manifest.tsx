import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Games',
    scenes: {
        Game368Hedgehogs: {
            name: '368Hedgehogs',
            import: () => import('./368Hedgehogs/368Hedgehogs'),
            projectBased: true,
            activityScope: 'Games',
        },
        FlappyHog: {
            name: 'FlappyHog',
            import: () => import('./FlappyHog/FlappyHog'),
            projectBased: true,
            activityScope: 'Games',
        },
        ShipIt: {
            name: 'Ship It',
            import: () => import('./frontend/ShipIt/ShipIt'),
            projectBased: true,
            activityScope: 'Games',
        },
    },
    routes: {
        '/games/368hedgehogs': ['Game368Hedgehogs', 'game368Hedgehogs'],
        '/games/flappyhog': ['FlappyHog', 'flappyHog'],
        '/games/shipit': ['ShipIt', 'shipIt'],
    },
    urls: {
        game368hedgehogs: (): string => `/games/368hedgehogs`,
        flappyHog: (): string => `/games/flappyhog`,
        shipIt: (): string => `/games/shipit`,
    },
    treeItemsGames: [
        {
            path: '368 Hedgehogs',
            href: urls.game368hedgehogs(),
        },
        {
            path: 'Flappy Hog',
            href: '/games/flappyhog',
        },
        {
            path: 'Ship It',
            href: urls.shipIt(),
        },
    ],
}
