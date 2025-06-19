import { IconCursor } from '@posthog/icons'
import { FEATURE_FLAGS, PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Messaging',
    scenes: {
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
        '/messaging/campaigns/:id/:tab': ['MessagingCampaign', 'messagingCampaignTab'],
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
        '/messaging': '/messaging/campaigns',
        '/messaging/campaigns/new': '/messaging/campaigns/new/overview',
    },
    urls: {
        messagingCampaigns: (): string => '/messaging/campaigns',
        messagingCampaign: (id: string): string => `/messaging/campaigns/${id}/overview`,
        messagingCampaignTab: (id?: string, tab?: string): string =>
            `/messaging/campaigns/${id || 'new'}/${tab || 'overview'}`,
        messagingCampaignNew: (): string => '/messaging/campaigns/new/overview',
        messagingLibrary: (): string => '/messaging/library',
        messagingLibraryMessage: (id: string): string => `/messaging/library/messages/${id}`,
        messagingLibraryTemplate: (id?: string): string => `/messaging/library/templates/${id}`,
        messagingLibraryTemplateNew: (): string => '/messaging/library/templates/new',
        messagingLibraryTemplateFromMessage: (id?: string): string =>
            `/messaging/library/templates/new?messageId=${id}`,
    },
    fileSystemTypes: {
        messaging: {
            name: 'Campaign',
            icon: <IconCursor />,
            iconColor: ['var(--product-messaging-light)'],
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
            category: 'Tools',
            tags: ['alpha'],
            /**
             * We'll keep early-access flag (FEATURE_FLAGS.MESSAGING) enabled but use this
             * automation flag for sidebar visibility to enable internal dogfooding
             */
            flag: FEATURE_FLAGS.MESSAGING_AUTOMATION,
        },
    ],
}
