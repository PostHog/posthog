import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { ActivityScope, FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Logs',
    scenes: {
        Logs: {
            import: () => import('./frontend/LogsScene'),
            projectBased: true,
            name: 'Logs',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
            iconType: 'logs',
            description: 'Monitor and analyze your logs to understand and fix issues.',
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
            category: ProductItemCategory.BEHAVIOR,
            iconType: 'logs' as FileSystemIconType,
            iconColor: ['var(--color-product-logs-light)'] as FileSystemIconColor,
            href: urls.logs(),
            sceneKey: 'Logs',
        },
    ],
}
