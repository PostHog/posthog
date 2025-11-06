import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Synthetic Monitoring',
    scenes: {
        SyntheticMonitoring: {
            name: 'Synthetic Monitoring',
            import: () => import('./frontend/SyntheticMonitoring'),
            projectBased: true,
            iconType: 'synthetic_monitoring',
            description: 'Monitor your endpoints and track uptime, latency, and performance from multiple regions',
        },
        SyntheticMonitor: {
            name: 'Monitor',
            import: () => import('./frontend/SyntheticMonitor'),
            projectBased: true,
        },
    },
    routes: {
        '/synthetic-monitoring': ['SyntheticMonitoring', 'syntheticMonitoring'],
        '/synthetic-monitoring/:id': ['SyntheticMonitor', 'syntheticMonitor'],
    },
    redirects: {},
    urls: {
        syntheticMonitoring: (): string => '/synthetic-monitoring',
        syntheticMonitor:
            /** @param id A UUID or 'new'. ':id' for routing. */
            (id: string | 'new'): string => `/synthetic-monitoring/${id}`,
    },
    fileSystemTypes: {
        synthetic_monitor: {
            name: 'Synthetic monitor',
            iconType: 'monitor' as FileSystemIconType,
            href: (ref: string) => urls.syntheticMonitor(ref),
            iconColor: [
                'var(--color-product-synthetic-monitoring-light)',
                'var(--color-product-synthetic-monitoring-dark)',
            ],
            filterKey: 'synthetic_monitor',
        },
    },
    treeItemsNew: [
        {
            path: `Synthetic monitor`,
            type: 'synthetic_monitor',
            href: urls.syntheticMonitor('new'),
            iconType: 'monitor' as FileSystemIconType,
            iconColor: [
                'var(--color-product-synthetic-monitoring-light)',
                'var(--color-product-synthetic-monitoring-dark)',
            ] as FileSystemIconColor,
        },
    ],
    treeItemsProducts: [
        {
            path: 'Synthetic monitoring',
            category: 'Unreleased',
            type: 'synthetic_monitor',
            href: urls.syntheticMonitoring(),
            iconType: 'synthetic_monitoring' as FileSystemIconType,
            iconColor: [
                'var(--color-product-synthetic-monitoring-light)',
                'var(--color-product-synthetic-monitoring-dark)',
            ] as FileSystemIconColor,
            flag: FEATURE_FLAGS.SYNTHETIC_MONITORING,
            tags: ['alpha'],
            sceneKey: 'SyntheticMonitoring',
        },
    ],
}
