import { IconMegaphone } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Messaging',
    scenes: {
        MessagingAutomations: {
            import: () => import('./frontend/Automations'),
            name: 'Automations',
            projectBased: true,
        },
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
        MessagingLibrary: {
            import: () => import('./frontend/Library'),
            name: 'Library',
            projectBased: true,
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/messaging/automations': ['MessagingAutomations', 'messagingAutomations'],
        '/messaging/automations/:id': ['MessagingAutomations', 'messagingAutomation'],
        '/messaging/automations/new': ['MessagingAutomations', 'messagingAutomationNew'],
        '/messaging/providers': ['MessagingProviders', 'messagingProviders'],
        '/messaging/providers/:id': ['MessagingProviders', 'messagingProvider'],
        '/messaging/providers/new': ['MessagingProviders', 'messagingProviderNew'],
        '/messaging/providers/new/*': ['MessagingProviders', 'messagingProviderNew'],
        '/messaging/broadcasts': ['MessagingBroadcasts', 'messagingBroadcasts'],
        '/messaging/broadcasts/:id': ['MessagingBroadcasts', 'messagingBroadcast'],
        '/messaging/broadcasts/new': ['MessagingBroadcasts', 'messagingBroadcastNew'],
        '/messaging/library': ['MessagingLibrary', 'messagingLibrary'],
        '/messaging/library/new': ['MessagingLibrary', 'messagingLibraryNew'],
        '/messaging/library/:id': ['MessagingLibrary', 'messagingLibraryTemplate'],
    },
    redirects: {
        '/messaging': '/messaging/broadcasts',
    },
    urls: {
        messagingAutomations: (): string => '/messaging/automations',
        messagingAutomation: (id?: string): string => `/messaging/automations/${id}`,
        messagingAutomationNew: (): string => '/messaging/automations/new',
        messagingBroadcasts: (): string => '/messaging/broadcasts',
        messagingBroadcast: (id?: string): string => `/messaging/broadcasts/${id}`,
        messagingBroadcastNew: (): string => '/messaging/broadcasts/new',
        messagingProviders: (): string => '/messaging/providers',
        messagingProvider: (id?: string): string => `/messaging/providers/${id}`,
        messagingProviderNew: (template?: string): string =>
            '/messaging/providers/new' + (template ? `/${template}` : ''),
        messagingLibrary: (): string => '/messaging/library',
        messagingLibraryNew: (): string => '/messaging/library/new',
        messagingLibraryTemplate: (id?: string): string => `/messaging/library/${id}`,
    },
    fileSystemTypes: {
        broadcast: {
            icon: <IconMegaphone />,
            href: (ref: string) => urls.messagingBroadcast(ref),
        },
    },
    treeItems: [
        {
            path: `Create new/Broadcast`,
            type: 'broadcast',
            href: () => urls.messagingBroadcastNew(),
        },
    ],
}
