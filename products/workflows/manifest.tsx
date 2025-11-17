import { FEATURE_FLAGS, PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

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
            description: 'Create and manage your workflows',
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
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/workflows': ['Workflows', 'workflows'],
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
            href: urls.workflows(),
            type: 'workflows',
            visualOrder: PRODUCT_VISUAL_ORDER.workflows,
            category: 'Tools',
            tags: ['beta'],
            flag: FEATURE_FLAGS.WORKFLOWS,
            iconType: 'workflows',
            iconColor: ['var(--color-product-workflows-light)'] as FileSystemIconColor,
            sceneKey: 'Workflows',
        },
    ],
}
