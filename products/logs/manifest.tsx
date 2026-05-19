import { combineUrl } from 'kea-router'

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
            name: 'New drop rule',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
        },
        LogsSamplingDetail: {
            import: () => import('./frontend/scenes/LogsSamplingDetailScene/LogsSamplingDetailScene'),
            projectBased: true,
            name: 'Drop rule',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
        },
    },
    routes: {
        '/logs': ['Logs', 'logs'],
        '/logs/alerts/:id': ['LogsAlertDetail', 'logsAlertDetail'],
        '/logs/drop-rules/new': ['LogsSamplingNew', 'logsSamplingNew'],
        '/logs/drop-rules/:id': ['LogsSamplingDetail', 'logsSamplingDetail'],
    },
    redirects: {
        '/logs/sampling/new': (_params, searchParams, hashParams) =>
            combineUrl('/logs/drop-rules/new', searchParams, hashParams).url,
        '/logs/sampling/:id': (params, searchParams, hashParams) =>
            combineUrl(`/logs/drop-rules/${params.id}`, searchParams, hashParams).url,
    },
    urls: {
        logs: (): string => '/logs',
        logsAlertDetail: (id: string, tab?: string): string =>
            tab ? `/logs/alerts/${id}?tab=${tab}` : `/logs/alerts/${id}`,
        logsSamplingNew: (): string => '/logs/drop-rules/new',
        logsSamplingDetail: (id: string): string => `/logs/drop-rules/${id}`,
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
