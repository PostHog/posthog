import { ProductItemCategory } from '~/queries/schema/schema-general'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Uptime',
    scenes: {
        Uptime: {
            name: 'Uptime',
            projectBased: true,
            import: () => import('./frontend/scenes/UptimeScene'),
        },
        UptimeMonitor: {
            name: 'Monitor',
            projectBased: true,
            import: () => import('./frontend/scenes/UptimeMonitorScene'),
        },
    },
    routes: {
        '/uptime': ['Uptime', 'uptime'],
        '/uptime/:id': ['UptimeMonitor', 'uptimeMonitor'],
    },
    redirects: {},
    urls: {
        uptime: (): string => '/uptime',
        uptimeMonitor: (id: string): string => `/uptime/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Uptime',
            category: ProductItemCategory.BEHAVIOR,
            href: '/uptime',
            iconType: 'uptime',
            sceneKey: 'Uptime',
            intents: [],
        },
    ],
}
