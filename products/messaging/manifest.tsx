import { IconMessage } from '@posthog/icons'
import { FEATURE_FLAGS, PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Messaging',
    scenes: {
        MessagingBroadcasts: {
            import: () => import('./frontend/Broadcasts'),
            name: 'Messaging',
            projectBased: true,
        },
        MessagingLibrary: {
            import: () => import('./frontend/TemplateLibrary/MessageLibrary'),
            name: 'Messaging',
            projectBased: true,
        },
        MessagingCampaigns: {
            import: () => import('./frontend/Campaigns/Campaigns'),
            name: 'Messaging',
            projectBased: true,
        },
        MessagingCampaign: {
            import: () => import('./frontend/Campaigns/CampaignScene'),
            name: 'Messaging',
            projectBased: true,
        },
        MessagingLibraryTemplate: {
            import: () => import('./frontend/TemplateLibrary/MessageTemplate'),
            name: 'Messaging',
            projectBased: true,
        },
        MessageSenders: {
            import: () => import('./frontend/Senders/MessageSenders'),
            name: 'Messaging',
            projectBased: true,
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/messaging/campaigns': ['MessagingCampaigns', 'messagingCampaigns'],
        '/messaging/campaigns/:id': ['MessagingCampaign', 'messagingCampaign'],
        '/messaging/campaigns/new': ['MessagingCampaign', 'messagingCampaignNew'],
        '/messaging/campaigns/:id/:tab': ['MessagingCampaign', 'messagingCampaignTab'],
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
        '/messaging/senders': ['MessageSenders', 'messageSenders'],
    },
    redirects: {
        '/messaging': '/messaging/broadcasts',
        '/messaging/campaigns/new': '/messaging/campaigns/new/trigger',
    },
    urls: {
        messagingCampaigns: (): string => '/messaging/campaigns',
        messagingCampaign: (id?: string): string => `/messaging/campaigns/${id}`,
        messagingCampaignTab: (id?: string, tab?: string): string => `/messaging/campaigns/${id}/${tab}`,
        messagingCampaignNew: (): string => '/messaging/campaigns/new',
        messagingBroadcasts: (): string => '/messaging/broadcasts',
        messagingBroadcast: (id?: string): string => `/messaging/broadcasts/${id}`,
        messagingBroadcastNew: (): string => '/messaging/broadcasts/new',
        messagingLibrary: (): string => '/messaging/library',
        messagingLibraryMessage: (id: string): string => `/messaging/library/messages/${id}`,
        messagingLibraryTemplate: (id?: string): string => `/messaging/library/templates/${id}`,
        messagingLibraryTemplateNew: (): string => '/messaging/library/templates/new',
        messagingLibraryTemplateFromMessage: (id?: string): string =>
            `/messaging/library/templates/new?messageId=${id}`,
    },
    fileSystemTypes: {
        messaging: {
            name: 'Messaging',
            icon: <IconMessage />,
            href: (ref: string) => urls.messagingCampaign(ref),
            filterKey: 'messaging',
        },
    },
    treeItemsProducts: [
        {
            path: 'Messaging',
            href: urls.messagingCampaigns(),
            type: 'messaging',
            visualOrder: PRODUCT_VISUAL_ORDER.messaging,
            tags: ['alpha'],
            flag: FEATURE_FLAGS.MESSAGING,
        },
    ],
}
