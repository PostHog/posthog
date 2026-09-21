import { FEATURE_FLAGS } from 'lib/constants'
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
            docsHref: 'https://posthog.com/docs/workflows',
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
        Broadcasts: {
            import: () => import('./frontend/Broadcasts/BroadcastsScene'),
            name: 'Broadcasts',
            iconType: 'broadcasts',
            projectBased: true,
            description: 'Send a one-time or scheduled email to a group of people',
        },
        Broadcast: {
            import: () => import('./frontend/Broadcasts/BroadcastScene'),
            name: 'Broadcasts',
            iconType: 'broadcasts',
            projectBased: true,
            description: 'Send a one-time or scheduled email to a group of people',
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/workflows': ['Workflows', 'workflows'],
        // kea-router matches in declaration order, so every literal 'broadcasts' route is listed
        // before the ':tab' and ':id/:tab' patterns that would otherwise swallow it.
        '/workflows/broadcasts': ['Broadcasts', 'broadcasts'],
        '/workflows/broadcasts/new': ['Broadcast', 'broadcast'],
        '/workflows/broadcasts/:id': ['Broadcast', 'broadcast'],
        '/workflows/:tab': ['Workflows', 'workflows'],
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
            category: ProductItemCategory.MESSAGING,
            iconType: 'workflows',
            iconColor: ['var(--color-product-workflows-light)'] as FileSystemIconColor,
            sceneKey: 'Workflows',
        },
        {
            path: 'Broadcasts',
            intents: [ProductKey.WORKFLOWS],
            href: urls.broadcasts(),
            type: 'broadcasts',
            category: ProductItemCategory.MESSAGING,
            iconType: 'broadcasts',
            iconColor: ['var(--color-product-workflows-light)'] as FileSystemIconColor,
            flag: FEATURE_FLAGS.BROADCASTS,
            tags: ['beta'],
            sceneKey: 'Broadcasts',
        },
    ],
}
