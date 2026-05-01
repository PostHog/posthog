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
        LogsAlertNew: {
            import: () => import('./frontend/scenes/LogsAlertNewScene/LogsAlertNewScene'),
            projectBased: true,
            name: 'New alert',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
        },
        LogsAlertDetail: {
            import: () => import('./frontend/scenes/LogsAlertDetailScene/LogsAlertDetailScene'),
            projectBased: true,
            name: 'Alert',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
        },
        LogsSamplingNew: {
            import: () => import('./frontend/scenes/LogsSamplingNewScene/LogsSamplingNewScene'),
            projectBased: true,
            name: 'New sampling rule',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
        },
        LogsSamplingDetail: {
            import: () => import('./frontend/scenes/LogsSamplingDetailScene/LogsSamplingDetailScene'),
            projectBased: true,
            name: 'Sampling rule',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
        },
    },
    routes: {
        '/logs': ['Logs', 'logs'],
        '/logs/alerts/new': ['LogsAlertNew', 'logsAlertNew'],
        '/logs/alerts/:id': ['LogsAlertDetail', 'logsAlertDetail'],
        '/logs/sampling/new': ['LogsSamplingNew', 'logsSamplingNew'],
        '/logs/sampling/:id': ['LogsSamplingDetail', 'logsSamplingDetail'],
    },
    redirects: {},
    urls: {
        logs: (): string => '/logs',
        logsAlertNew: (): string => '/logs/alerts/new',
        logsAlertDetail: (id: string, tab?: string): string =>
            tab ? `/logs/alerts/${id}?tab=${tab}` : `/logs/alerts/${id}`,
        logsSamplingNew: (): string => '/logs/sampling/new',
        logsSamplingDetail: (id: string): string => `/logs/sampling/${id}`,
    },
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
