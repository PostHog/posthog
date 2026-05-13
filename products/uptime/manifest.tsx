import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Uptime',
    scenes: {
        Uptime: {
            name: 'Uptime',
            projectBased: true,
            import: () => import('./frontend/scenes/UptimeScene'),
        },
    },
    routes: {
        '/uptime': ['Uptime', 'uptime'],
    },
    redirects: {},
    urls: {
        uptime: (): string => '/uptime',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
