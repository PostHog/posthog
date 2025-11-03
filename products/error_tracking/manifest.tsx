import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Error tracking',
    scenes: {
        ErrorTracking: {
            import: () => import('./frontend/scenes/ErrorTrackingScene/ErrorTrackingScene'),
            projectBased: true,
            name: 'Error tracking',
            defaultDocsPath: '/docs/error-tracking',
            iconType: 'error_tracking',
            description: 'Track and analyze your error tracking data to understand and fix issues.',
        },
        ErrorTrackingIssue: {
            import: () => import('./frontend/scenes/ErrorTrackingIssueScene/ErrorTrackingIssueScene'),
            projectBased: true,
            name: 'Error tracking issue',
            layout: 'app-full-scene-height',
        },
        ErrorTrackingIssueFingerprints: {
            import: () =>
                import('./frontend/scenes/ErrorTrackingFingerprintsScene/ErrorTrackingIssueFingerprintsScene'),
            projectBased: true,
            name: 'Error tracking issue fingerprints',
        },
        ErrorTrackingConfiguration: {
            import: () => import('./frontend/scenes/ErrorTrackingConfigurationScene/ErrorTrackingConfigurationScene'),
            projectBased: true,
            name: 'Error tracking configuration',
        },
    },
    routes: {
        '/error_tracking': ['ErrorTracking', 'errorTracking'],
        '/error_tracking/configuration': ['ErrorTrackingConfiguration', 'errorTrackingConfiguration'],
        '/error_tracking/:id': ['ErrorTrackingIssue', 'errorTrackingIssue'],
        '/error_tracking/:id/fingerprints': ['ErrorTrackingIssueFingerprints', 'errorTrackingIssueFingerprints'],
        '/error_tracking/alerts/:id': ['HogFunction', 'errorTrackingAlert'],
        '/error_tracking/alerts/new/:templateId': ['HogFunction', 'errorTrackingAlertNew'],
    },
    redirects: {},
    urls: {
        errorTracking: (params = {}): string => combineUrl('/error_tracking', params).url,
        errorTrackingConfiguration: (params = {}): string => combineUrl('/error_tracking/configuration', params).url,
        /** @param id A UUID or 'new'. ':id' for routing. */
        errorTrackingIssue: (id: string, params: { timestamp?: string; fingerprint?: string } = {}): string =>
            combineUrl(`/error_tracking/${id}`, params).url,
        errorTrackingIssueFingerprints: (id: string): string => `/error_tracking/${id}/fingerprints`,
        errorTrackingAlert: (id: string): string => `/error_tracking/alerts/${id}`,
        errorTrackingAlertNew: (templateId: string): string => `/error_tracking/alerts/new/${templateId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Error tracking',
            category: 'Behavior',
            type: 'error_tracking',
            iconType: 'error_tracking' as FileSystemIconType,
            iconColor: [
                'var(--color-product-error-tracking-light)',
                'var(--color-product-error-tracking-dark)',
            ] as FileSystemIconColor,
            href: urls.errorTracking(),
            sceneKey: 'ErrorTracking',
        },
    ],
}
