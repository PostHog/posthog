import { FEATURE_FLAGS, PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'
import type { MessagingSceneTab } from './frontend/MessagingScene'

export const manifest: ProductManifest = {
    name: 'Messaging',
    scenes: {
        Messaging: {
            import: () => import('./frontend/MessagingScene'),
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
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/messaging/:tab': ['Messaging', 'messagingCampaigns'],
        '/messaging/campaigns/:id/:tab': ['MessagingCampaign', 'messagingCampaignTab'],
        '/messaging/library/templates/:id': ['MessagingLibraryTemplate', 'messagingLibraryTemplate'],
        '/messaging/library/templates/new': ['MessagingLibraryTemplate', 'messagingLibraryTemplate'],
        '/messaging/library/templates/new?messageId=:messageId': [
            'MessagingLibraryTemplate',
            'messagingLibraryTemplateFromMessage',
        ],
    },
    redirects: {
        '/messaging': '/messaging/campaigns',
        '/messaging/campaigns/new': '/messaging/campaigns/new/workflow',
    },
    urls: {
        messaging: (tab?: MessagingSceneTab): string => `/messaging/${tab || 'campaigns'}`,
        messagingCampaign: (id: string, tab?: string): string => `/messaging/campaigns/${id}/${tab || 'workflow'}`,
        messagingCampaignNew: (): string => '/messaging/campaigns/new/workflow',
        messagingLibraryMessage: (id: string): string => `/messaging/library/messages/${id}`,
        messagingLibraryTemplate: (id?: string): string => `/messaging/library/templates/${id}`,
        messagingLibraryTemplateNew: (): string => '/messaging/library/templates/new',
        messagingLibraryTemplateFromMessage: (id?: string): string =>
            `/messaging/library/templates/new?messageId=${id}`,
    },
    fileSystemTypes: {
        messaging: {
            name: 'Campaign',
            iconType: 'messaging',
            iconColor: ['var(--color-product-messaging-light)'] as FileSystemIconColor,
            href: (ref: string) => urls.messagingCampaign(ref),
            filterKey: 'messaging',
        },
    },
    treeItemsProducts: [
        {
            path: 'Messaging',
            href: urls.messaging(),
            type: 'messaging',
            visualOrder: PRODUCT_VISUAL_ORDER.messaging,
            category: 'Unreleased',
            tags: ['alpha'],
            flag: FEATURE_FLAGS.MESSAGING,
            iconType: 'messaging',
            iconColor: ['var(--color-product-messaging-light)'] as FileSystemIconColor,
        },
    ],
}
