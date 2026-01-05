import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Logs',
    scenes: {
        Logs: {
            import: () => import('./frontend/LogsScene'),
            projectBased: true,
            name: 'Logs',
            activityScope: 'Logs',
            layout: 'app-container',
            iconType: 'logs',
            description: 'Monitor and analyze your logs to understand and fix issues.',
            defaultDocsPath: '/docs/logs',
            changelogTeamSlug: 'Logs',
        },
    },
    routes: {
        '/logs': ['Logs', 'logs'],
    },
    redirects: {},
    urls: { logs: (): string => '/logs' },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Logs',
            intents: [ProductKey.LOGS],
            category: 'Behavior',
            iconType: 'logs' as FileSystemIconType,
            iconColor: ['var(--color-product-logs-light)'] as FileSystemIconColor,
            href: urls.logs(),
            tags: ['beta'],
            sceneKey: 'Logs',
        },
    ],
}
