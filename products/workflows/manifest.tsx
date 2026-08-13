import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'
import type { WorkflowsSceneTab } from './frontend/WorkflowsScene'

export const manifest: ProductManifest = {
    name: 'Workflows',
    scenes: {
        Workflows: {
            import: () => import('./frontend/WorkflowsScene'),
            name: 'Workflows',
            iconType: 'workflows',
            projectBased: true,
            description: 'Automate user communication and internal processes',
        },
        Workflow: {
            import: () => import('./frontend/Workflows/WorkflowScene'),
            name: 'Workflows',
            iconType: 'workflows',
            projectBased: true,
        },
        WorkflowsLibraryTemplate: {
            import: () => import('./frontend/TemplateLibrary/MessageTemplate'),
            name: 'Workflows',
            iconType: 'workflows',
            projectBased: true,
        },
        Broadcast: {
            import: () => import('./frontend/Broadcasts/BroadcastScene'),
            name: 'Broadcast',
            iconType: 'workflows',
            projectBased: true,
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/workflows': ['Workflows', 'workflows'],
        '/workflows/:tab': ['Workflows', 'workflows'],
        // Broadcast routes must precede '/workflows/:id/:tab': kea-router matches routes in
        // declaration order, so the literal 'broadcasts' segment only wins if it's listed first.
        '/workflows/broadcasts/new': ['Broadcast', 'broadcast'],
        '/workflows/broadcasts/:id': ['Broadcast', 'broadcast'],
        '/workflows/:id/:tab': ['Workflow', 'workflowTab'],
        '/workflows/library/templates/:id': ['WorkflowsLibraryTemplate', 'workflowsLibraryTemplate'],
        '/workflows/library/templates/new': ['WorkflowsLibraryTemplate', 'workflowsLibraryTemplate'],
        '/workflows/library/templates/new?messageId=:messageId': [
            'WorkflowsLibraryTemplate',
            'workflowsLibraryTemplateFromMessage',
        ],
    },
    urls: {
        workflows: (tab?: WorkflowsSceneTab): string => `/workflows${tab ? `/${tab}` : ''}`,
        broadcasts: (): string => '/workflows/broadcasts',
        broadcastNew: (): string => '/workflows/broadcasts/new',
        broadcast: (id: string): string => `/workflows/broadcasts/${id}`,
        workflow: (id: string, tab: string): string => `/workflows/${id}/${tab}`,
        workflowNew: (): string => '/workflows/new/workflow',
        workflowsLibraryMessage: (id: string): string => `/workflows/library/messages/${id}`,
        workflowsLibraryTemplate: (id?: string): string => `/workflows/library/templates/${id}`,
        workflowsLibraryTemplateNew: (): string => '/workflows/library/templates/new',
        workflowsLibraryTemplateFromMessage: (id?: string): string =>
            `/workflows/library/templates/new?messageId=${id}`,
    },
    fileSystemTypes: {
        workflows: {
            name: 'Workflow',
            iconType: 'workflows',
            iconColor: ['var(--color-product-workflows-light)'] as FileSystemIconColor,
            href: (ref: string) => urls.workflow(ref, 'workflow'),
            filterKey: 'workflows',
        },
    },
    treeItemsProducts: [
        {
            path: 'Workflows',
            intents: [ProductKey.WORKFLOWS],
            href: urls.workflows(),
            type: 'workflows',
            category: ProductItemCategory.TOOLS,
            iconType: 'workflows',
            iconColor: ['var(--color-product-workflows-light)'] as FileSystemIconColor,
            sceneKey: 'Workflows',
        },
    ],
}
