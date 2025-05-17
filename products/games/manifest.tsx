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
        GameHogWars: {
            name: 'HogWars',
            import: () => import('./HogWars/HogWars'),
            projectBased: true,
            activityScope: 'Games',
        },
    },
    routes: {
        '/games/368hedgehogs': ['Game368Hedgehogs', 'game368Hedgehogs'],
        '/games/hogwars': ['GameHogWars', 'gameHogWars'],
    },
    urls: {
        game368hedgehogs: (): string => `/games/368hedgehogs`,
        gameHogWars: (): string => `/games/hogwars`,
    },
    treeItemsGames: [
        {
            path: '368 Hedgehogs',
            href: urls.game368hedgehogs(),
        },
        {
            path: 'HogWars',
            href: urls.gameHogWars(),
        },
    ],
}
