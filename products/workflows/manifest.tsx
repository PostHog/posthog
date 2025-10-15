import { FEATURE_FLAGS, PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'
import type { WorkflowsSceneTab } from './frontend/WorkflowScene'

export const manifest: ProductManifest = {
    name: 'Workflows',
    scenes: {
        Workflows: {
            import: () => import('./frontend/WorkflowScene'),
            name: 'Workflows',
            projectBased: true,
        },
        Workflow: {
            import: () => import('./frontend/Workflows/WorkflowScene'),
            name: 'Workflows',
            projectBased: true,
        },
        WorkflowsLibraryTemplate: {
            import: () => import('./frontend/TemplateLibrary/MessageTemplate'),
            name: 'Workflows',
            projectBased: true,
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/messaging/:tab': ['Workflows', 'messagingWorkflows'],
        '/messaging/workflows/:id/:tab': ['Workflow', 'messagingWorkflowTab'],
        '/messaging/library/templates/:id': ['WorkflowsLibraryTemplate', 'messagingLibraryTemplate'],
        '/messaging/library/templates/new': ['WorkflowsLibraryTemplate', 'messagingLibraryTemplate'],
        '/messaging/library/templates/new?messageId=:messageId': [
            'WorkflowsLibraryTemplate',
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
            path: 'Workflows',
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
