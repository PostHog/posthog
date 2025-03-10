import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Messaging',
    scenes: {
        MessagingBroadcasts: {
            import: () => import('./frontend/Broadcasts'),
            name: 'Messaging',
            projectBased: true,
        },
        MessagingProviders: {
            import: () => import('./frontend/Providers'),
            name: 'Messaging',
            projectBased: true,
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/messaging/providers': ['MessagingProviders', 'messagingProviders'],
        '/messaging/providers/:id': ['MessagingProviders', 'messagingProvider'],
        '/messaging/providers/new': ['MessagingProviders', 'messagingProviderNew'],
        '/messaging/providers/new/*': ['MessagingProviders', 'messagingProviderNew'],
        '/messaging/broadcasts': ['MessagingBroadcasts', 'messagingBroadcasts'],
        '/messaging/broadcasts/:id': ['MessagingBroadcasts', 'messagingBroadcast'],
        '/messaging/broadcasts/new': ['MessagingBroadcasts', 'messagingBroadcastNew'],
    },
    redirects: {
        '/messaging': '/messaging/broadcasts',
    },
    urls: {
        messagingBroadcasts: (): string => '/messaging/broadcasts',
        messagingBroadcast: (id?: string): string => `/messaging/broadcasts/${id}`,
        messagingBroadcastNew: (): string => '/messaging/broadcasts/new',
        messagingProviders: (): string => '/messaging/providers',
        messagingProvider: (id?: string): string => `/messaging/providers/${id}`,
        messagingProviderNew: (template?: string): string => '/messaging/providers/new' + (template ? `/${template}` : ''),
    }
}
