import { FEATURE_FLAGS, PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'
import type { WorkflowsSceneTab } from './frontend/WorkflowScene'

export const manifest: ProductManifest = {
    name: 'Messaging',
    scenes: {
        Messaging: {
            import: () => import('./frontend/WorkflowScene'),
            name: 'Messaging',
            projectBased: true,
        },
        MessagingWorkflow: {
            import: () => import('./frontend/Workflows/WorkflowScene'),
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
        '/messaging/:tab': ['Messaging', 'messagingWorkflows'],
        '/messaging/workflows/:id/:tab': ['MessagingWorkflow', 'messagingWorkflowTab'],
        '/messaging/library/templates/:id': ['MessagingLibraryTemplate', 'messagingLibraryTemplate'],
        '/messaging/library/templates/new': ['MessagingLibraryTemplate', 'messagingLibraryTemplate'],
        '/messaging/library/templates/new?messageId=:messageId': [
            'MessagingLibraryTemplate',
            'messagingLibraryTemplateFromMessage',
        ],
    },
    redirects: {
        '/messaging': '/messaging/workflows',
        '/messaging/workflows/new': '/messaging/workflows/new/workflow',
    },
    urls: {
        messaging: (tab?: WorkflowsSceneTab): string => `/messaging/${tab || 'workflows'}`,
        messagingWorkflow: (id: string, tab?: string): string => `/messaging/workflows/${id}/${tab || 'workflow'}`,
        messagingWorkflowNew: (): string => '/messaging/workflows/new/workflow',
        messagingLibraryMessage: (id: string): string => `/messaging/library/messages/${id}`,
        messagingLibraryTemplate: (id?: string): string => `/messaging/library/templates/${id}`,
        messagingLibraryTemplateNew: (): string => '/messaging/library/templates/new',
        messagingLibraryTemplateFromMessage: (id?: string): string =>
            `/messaging/library/templates/new?messageId=${id}`,
    },
    fileSystemTypes: {
        messaging: {
            name: 'Workflow',
            iconType: 'messaging',
            iconColor: ['var(--color-product-messaging-light)'] as FileSystemIconColor,
            href: (ref: string) => urls.messagingWorkflow(ref),
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
