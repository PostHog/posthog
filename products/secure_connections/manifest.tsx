import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Secure connections',
    scenes: {
        SecureConnections: {
            import: () => import('./frontend/SecureConnectionsScene'),
            name: 'Secure connections',
            description: 'Connect PostHog to services on your private network.',
            projectBased: true,
        },
    },
    routes: {
        '/settings/project/secure-connections': ['SecureConnections', 'secureConnections'],
    },
    redirects: {},
    urls: {
        secureConnections: (): string => '/settings/project/secure-connections',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [],
}
