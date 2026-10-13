import { combineUrl } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { ActivityScope, FileSystemIconColor, ProductManifest } from '../../frontend/src/types'
import type { LogsSceneActiveTab } from './frontend/logsSceneLogic'

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
            docsHref: 'https://posthog.com/docs/logs',
        },
        LogsAlertDetail: {
            import: () => import('./frontend/scenes/LogsAlertDetailScene/LogsAlertDetailScene'),
            projectBased: true,
            name: 'Alert',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
        },
        LogsAlertNotificationDetail: {
            import: () => import('./frontend/scenes/LogsAlertNotificationDetailScene/LogsAlertNotificationDetailScene'),
            projectBased: true,
            name: 'Destination',
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
        LogsRetentionNew: {
            import: () => import('./frontend/scenes/LogsRetentionNewScene/LogsRetentionNewScene'),
            projectBased: true,
            name: 'New retention rule',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
        },
        LogsRetentionDetail: {
            import: () => import('./frontend/scenes/LogsRetentionDetailScene/LogsRetentionDetailScene'),
            projectBased: true,
            name: 'Retention rule',
            activityScope: ActivityScope.LOG,
            layout: 'app-container',
        },
    },
    routes: {
        '/logs': ['Logs', 'logs'],
        '/logs/alerts/:id': ['LogsAlertDetail', 'logsAlertDetail'],
        '/logs/alerts/:id/notifications/:hogFunctionId': ['LogsAlertNotificationDetail', 'logsAlertNotificationDetail'],
        '/logs/drop-rules/new': ['LogsSamplingNew', 'logsSamplingNew'],
        '/logs/drop-rules/:id': ['LogsSamplingDetail', 'logsSamplingDetail'],
        '/logs/retention-rules/new': ['LogsRetentionNew', 'logsRetentionNew'],
        '/logs/retention-rules/:id': ['LogsRetentionDetail', 'logsRetentionDetail'],
    },
    redirects: {
        '/logs/sampling/new': (_params, searchParams, hashParams) =>
            combineUrl('/logs/drop-rules/new', searchParams, hashParams).url,
        '/logs/sampling/:id': (params, searchParams, hashParams) =>
            combineUrl(`/logs/drop-rules/${params.id}`, searchParams, hashParams).url,
    },
    urls: {
        logs: (activeTab?: LogsSceneActiveTab): string => (activeTab ? `/logs?activeTab=${activeTab}` : '/logs'),
        logsAlertDetail: (id: string, tab?: string): string =>
            tab ? `/logs/alerts/${id}?tab=${tab}` : `/logs/alerts/${id}`,
        logsAlertNotificationDetail: (alertId: string, hogFunctionId: string): string =>
            `/logs/alerts/${alertId}/notifications/${hogFunctionId}`,
        logsSamplingNew: (): string => '/logs/drop-rules/new',
        logsSamplingDetail: (id: string): string => `/logs/drop-rules/${id}`,
        logsRetentionNew: (): string => '/logs/retention-rules/new',
        logsRetentionDetail: (id: string): string => `/logs/retention-rules/${id}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Logs',
            intents: [ProductKey.LOGS],
            category: ProductItemCategory.MONITORING,
            iconType: 'logs' as FileSystemIconType,
            iconColor: ['var(--color-product-logs-light)', 'var(--color-product-logs-dark)'] as FileSystemIconColor,
            href: urls.logs(),
            searchTabs: [
                { name: 'Alerts', href: urls.logs('alerts') },
                { name: 'SQL', href: urls.logs('sql') },
                {
                    name: 'Services',
                    href: urls.logs('services'),
                    flag: FEATURE_FLAGS.LOGS_SERVICES_VIEW,
                },
                {
                    name: 'Anomalies',
                    href: urls.logs('anomalies'),
                    flag: FEATURE_FLAGS.LOGS_ANOMALIES,
                },
            ],
            sceneKey: 'Logs',
        },
    ],
}
