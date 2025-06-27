import { combineUrl } from 'kea-router'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Error tracking',
    scenes: {
        ErrorTracking: {
            import: () => import('./frontend/ErrorTrackingScene'),
            projectBased: true,
            name: 'Error tracking',
            defaultDocsPath: '/docs/error-tracking',
        },
        ErrorTrackingIssue: {
            import: () => import('./frontend/ErrorTrackingIssueScene'),
            projectBased: true,
            name: 'Error tracking issue',
        },
        ErrorTrackingConfiguration: {
            import: () => import('./frontend/configuration/ErrorTrackingConfigurationScene'),
            projectBased: true,
            name: 'Error tracking configuration',
        },
    },
    routes: {
        '/error_tracking': ['ErrorTracking', 'errorTracking'],
        '/error_tracking/configuration': ['ErrorTrackingConfiguration', 'errorTrackingConfiguration'],
        '/error_tracking/:id': ['ErrorTrackingIssue', 'errorTrackingIssue'],
        '/error_tracking/alerts/:id': ['HogFunction', 'errorTrackingAlert'],
        '/error_tracking/alerts/new/:templateId': ['HogFunction', 'errorTrackingAlertNew'],
    },
    redirects: {},
    urls: {
        errorTracking: (params = {}): string => combineUrl('/error_tracking', params).url,
        errorTrackingConfiguration: (params = {}): string => combineUrl('/error_tracking/configuration', params).url,
        /** @param id A UUID or 'new'. ':id' for routing. */
        errorTrackingIssue: (id: string, fingerprint?: string): string =>
            combineUrl(`/error_tracking/${id}`, { fingerprint }).url,
        errorTrackingAlert: (id: string): string => `/error_tracking/alerts/${id}`,
        errorTrackingAlertNew: (templateId: string): string => `/error_tracking/alerts/new/${templateId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Error tracking',
            category: 'Behavior',
            iconType: 'errorTracking',
            href: urls.errorTracking(),
        },
    ],
}
