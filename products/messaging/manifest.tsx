import { IconMegaphone } from '@posthog/icons'
import { FEATURE_FLAGS } from 'lib/constants'
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
            import: () => import('./frontend/library/MessageLibrary'),
            name: 'Messaging',
            projectBased: true,
        },
        MessagingLibraryTemplate: {
            import: () => import('./frontend/library/MessageTemplate'),
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
        '/messaging/library/templates/:id': ['MessagingLibraryTemplate', 'messagingLibraryTemplate'],
        '/messaging/library/templates/new': ['MessagingLibraryTemplate', 'messagingLibraryTemplate'],
        '/messaging/library/templates/new?messageId=:messageId': [
            'MessagingLibraryTemplate',
            'messagingLibraryTemplateFromMessage',
        ],
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
        messagingLibraryTemplate: (id?: string): string => `/messaging/library/templates/${id}`,
        messagingLibraryTemplateFromMessage: (id?: string): string =>
            `/messaging/library/templates/new?messageId=${id}`,
    },
    fileSystemTypes: {
        'hog_function/broadcast': {
            icon: <IconMegaphone />,
            href: (ref: string) => urls.messagingBroadcast(ref),
        },
        'hog_function/campaign': {
            icon: <IconMegaphone />,
            href: (ref: string) => urls.messagingCampaign(ref),
        },
    },
    treeItemsNew: [
        {
            path: `Broadcast`,
            type: 'hog_function/broadcast',
            href: () => urls.messagingBroadcastNew(),
            flag: FEATURE_FLAGS.MESSAGING,
        },
        {
            path: `Campaign`,
            type: 'hog_function/campaign',
            href: () => urls.messagingCampaignNew(),
            flag: FEATURE_FLAGS.MESSAGING_AUTOMATION,
        },
    ],
}
