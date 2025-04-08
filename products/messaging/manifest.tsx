import { IconMegaphone } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Messaging',
    scenes: {
        MessagingCampaigns: {
            import: () => import('./frontend/Campaigns'),
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
        '/messaging/campaigns': ['MessagingCampaigns', 'messagingCampaigns'],
        '/messaging/campaigns/:id': ['MessagingCampaigns', 'messagingCampaign'],
        '/messaging/campaigns/new': ['MessagingCampaigns', 'messagingCampaignNew'],
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
        messagingCampaigns: (): string => '/messaging/campaigns',
        messagingCampaign: (id?: string): string => `/messaging/campaigns/${id}`,
        messagingCampaignNew: (): string => '/messaging/campaigns/new',
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
