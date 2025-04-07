import { IconMegaphone } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Messaging',
    scenes: {
        MessagingAutomations: {
            import: () => import('./frontend/Automations'),
            name: 'Messaging',
            projectBased: true,
        },
        MessagingBroadcasts: {
            import: () => import('./frontend/Broadcasts'),
            name: 'Messaging',
            projectBased: true,
        },
        MessagingLibrary: {
            import: () => import('./frontend/Library'),
            name: 'Messaging',
            projectBased: true,
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/messaging/automations': ['MessagingAutomations', 'messagingAutomations'],
        '/messaging/automations/:id': ['MessagingAutomations', 'messagingAutomation'],
        '/messaging/automations/new': ['MessagingAutomations', 'messagingAutomationNew'],
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
        messagingLibrary: (): string => '/messaging/library',
        messagingLibraryNew: (): string => '/messaging/library/new',
        messagingLibraryTemplate: (id?: string): string => `/messaging/library/${id}`,
    },
    fileSystemTypes: {
        'hog_function/broadcast': {
            icon: <IconMegaphone />,
            href: (ref: string) => urls.messagingBroadcast(ref),
        },
    },
    treeItemsNew: [
        {
            path: `Broadcast`,
            type: 'hog_function/broadcast',
            href: () => urls.messagingBroadcastNew(),
        },
    ],
}
