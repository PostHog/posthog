import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'
import type { MessagingNavTabKey } from './frontend/messagingTabs'
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
        Transactional: {
            import: () => import('./frontend/Transactional/TransactionalScene'),
            name: 'Transactional',
            iconType: 'transactional',
            projectBased: true,
            description: 'Send emails from your code with one API call',
        },
        WorkflowsEmailDomain: {
            import: () => import('./frontend/Channels/EmailDomain/EmailDomainScene'),
            name: 'Workflows',
            iconType: 'workflows',
            projectBased: true,
        },
    },
    routes: {
        // URL: [Scene, SceneKey]
        '/workflows': ['Workflows', 'workflows'],
        '/workflows/:tab': ['Workflows', 'workflows'],
        '/workflows/channels/email/:id': ['WorkflowsEmailDomain', 'workflowsEmailDomain'],
        '/workflows/:id/:tab': ['Workflow', 'workflowTab'],
        '/workflows/library/templates/:id': ['WorkflowsLibraryTemplate', 'workflowsLibraryTemplate'],
        '/workflows/library/templates/new': ['WorkflowsLibraryTemplate', 'workflowsLibraryTemplate'],
        '/workflows/library/templates/new?messageId=:messageId': [
            'WorkflowsLibraryTemplate',
            'workflowsLibraryTemplateFromMessage',
        ],
        '/broadcasts': ['Broadcasts', 'broadcasts'],
        // Literal tab paths, listed before '/broadcasts/:id' so a tab never opens as a broadcast id.
        '/broadcasts/library': ['Broadcasts', 'broadcasts'],
        '/broadcasts/channels': ['Broadcasts', 'broadcasts'],
        '/broadcasts/opt-outs': ['Broadcasts', 'broadcasts'],
        '/broadcasts/suppression': ['Broadcasts', 'broadcasts'],
        '/broadcasts/reputation': ['Broadcasts', 'broadcasts'],
        '/broadcasts/settings': ['Broadcasts', 'broadcasts'],
        '/broadcasts/calendar': ['Broadcasts', 'broadcasts'],
        '/transactional': ['Transactional', 'transactional'],
        '/transactional/library': ['Transactional', 'transactional'],
        '/transactional/channels': ['Transactional', 'transactional'],
        '/transactional/opt-outs': ['Transactional', 'transactional'],
        '/transactional/suppression': ['Transactional', 'transactional'],
        '/transactional/reputation': ['Transactional', 'transactional'],
        '/transactional/settings': ['Transactional', 'transactional'],
        '/transactional/new': ['Transactional', 'transactional'],
        // A template opened from a section's Templates tab stays in that section.
        '/transactional/library/templates/:id': ['WorkflowsLibraryTemplate', 'workflowsLibraryTemplate'],
        '/broadcasts/library/templates/:id': ['WorkflowsLibraryTemplate', 'workflowsLibraryTemplate'],
        // kea-router matches in declaration order, so the literal 'new' comes before ':id'.
        '/broadcasts/new': ['Broadcast', 'broadcast'],
        '/broadcasts/:id': ['Broadcast', 'broadcast'],
    },
    urls: {
        workflows: (tab?: WorkflowsSceneTab): string => `/workflows${tab ? `/${tab}` : ''}`,
        workflow: (id: string, tab: string): string => `/workflows/${id}/${tab}`,
        workflowNew: (): string => '/workflows/new/workflow',
        workflowsEmailDomain: (id: string | number): string => `/workflows/channels/email/${id}`,
        workflowsLibraryMessage: (id: string): string => `/workflows/library/messages/${id}`,
        workflowsLibraryTemplate: (id?: string): string => `/workflows/library/templates/${id}`,
        workflowsLibraryTemplateNew: (): string => '/workflows/library/templates/new',
        workflowsLibraryTemplateFromMessage: (id?: string): string =>
            `/workflows/library/templates/new?messageId=${id}`,
        broadcasts: (tab?: MessagingNavTabKey | 'calendar'): string => `/broadcasts${tab ? `/${tab}` : ''}`,
        broadcast: (id: string): string => `/broadcasts/${id}`,
        broadcastNew: (): string => '/broadcasts/new',
        transactional: (tab?: MessagingNavTabKey): string => `/transactional${tab ? `/${tab}` : ''}`,
        transactionalNew: (): string => '/transactional/new',
        transactionalTemplate: (id: string): string => `/transactional/library/templates/${id}`,
        broadcastsTemplate: (id: string): string => `/broadcasts/library/templates/${id}`,
    },
    fileSystemTypes: {
        workflows: {
            name: 'Workflow',
            iconType: 'workflows',
            iconColor: ['var(--color-product-workflows-light)'] as FileSystemIconColor,
            href: (ref: string) => urls.workflow(ref, 'workflow'),
            listHref: () => urls.workflows(),
            filterKey: 'workflows',
        },
    },
    treeItemsProducts: [
        {
            path: 'Workflows',
            intents: [ProductKey.WORKFLOWS],
            href: urls.workflows(),
            searchTabs: [
                { name: 'Library', href: urls.workflows('library') },
                { name: 'Channels', href: urls.workflows('channels') },
                { name: 'Opt-outs', href: urls.workflows('opt-outs') },
                { name: 'Suppression list', href: urls.workflows('suppression') },
                { name: 'Reputation', href: urls.workflows('reputation') },
                { name: 'Settings', href: urls.workflows('settings') },
            ],
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
            iconColor: ['var(--color-product-broadcasts-light)', 'var(--color-product-broadcasts-dark)'],
            sceneKey: 'Broadcasts',
        },
        {
            path: 'Transactional',
            intents: [ProductKey.WORKFLOWS],
            href: urls.transactional(),
            type: 'transactional',
            category: ProductItemCategory.MESSAGING,
            iconType: 'transactional',
            iconColor: ['var(--color-product-workflows-light)', 'var(--color-product-workflows-dark)'],
            sceneKey: 'Transactional',
            flag: FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API,
        },
    ],
}
