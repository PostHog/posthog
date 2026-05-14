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
        UptimeStatusPage: {
            name: 'Status page',
            projectBased: true,
            import: () => import('./frontend/scenes/statusPage/StatusPageScene'),
        },
        UptimePublicStatusPage: {
            name: 'Status',
            projectBased: false,
            organizationBased: false,
            allowUnauthenticated: true,
            layout: 'plain',
            import: () => import('./frontend/scenes/statusPage/PublicStatusPageScene'),
        },
    },
    routes: {
        '/uptime': ['Uptime', 'uptime'],
        // Status-pages route must be declared before the generic /uptime/:id below so the
        // router prefers the literal `status-pages` segment over treating it as a monitor id.
        '/uptime/status-pages/:id': ['UptimeStatusPage', 'uptimeStatusPage'],
        '/uptime/:id': ['UptimeMonitor', 'uptimeMonitor'],
        '/status/:slug': ['UptimePublicStatusPage', 'uptimePublicStatusPage'],
    },
    redirects: {},
    urls: {
        uptime: (): string => '/uptime',
        uptimeMonitor: (id: string): string => `/uptime/${id}`,
        uptimeStatusPage: (id: string): string => `/uptime/status-pages/${id}`,
        uptimePublicStatusPage: (slug: string): string => `/status/${slug}`,
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
        },
    ],
}
