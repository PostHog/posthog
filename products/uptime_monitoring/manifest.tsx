import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Uptime monitoring',
    scenes: {
        UptimeMonitoring: {
            name: 'Uptime monitoring',
            import: () => import('./frontend/scenes/UptimeMonitoringScene/UptimeMonitoringScene'),
            projectBased: true,
            description: 'Check that your sites and endpoints respond, and find out when they go down.',
            iconType: 'uptime_monitoring',
        },
    },
    routes: {
        '/uptime-monitoring': ['UptimeMonitoring', 'uptimeMonitoring'],
    },
    redirects: {},
    urls: {
        uptimeMonitoring: (): string => '/uptime-monitoring',
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Uptime monitoring',
            intents: [ProductKey.UPTIME_MONITORING],
            category: ProductItemCategory.UNRELEASED,
            iconType: 'uptime_monitoring',
            href: urls.uptimeMonitoring(),
            searchKeywords: ['uptime', 'status', 'health check', 'synthetics', 'ping'],
            flag: FEATURE_FLAGS.UPTIME_MONITORING,
            tags: ['alpha'],
            sceneKey: 'UptimeMonitoring',
        },
    ],
}
