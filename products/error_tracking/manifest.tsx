import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { DateRange, FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest, UniversalFiltersGroup } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Error tracking',
    scenes: {
        ErrorTracking: {
            import: () => import('./frontend/scenes/ErrorTrackingScene/ErrorTrackingScene'),
            projectBased: true,
            name: 'Error tracking',
            iconType: 'error_tracking',
            description: 'Track and analyze your error tracking data to understand and fix issues.',
        },
        ErrorTrackingIssue: {
            import: () => import('./frontend/scenes/ErrorTrackingIssueScene/ErrorTrackingIssueScene'),
            projectBased: true,
            name: 'Error tracking issue',
            layout: 'app-raw',
        },
        ErrorTrackingIssueFingerprints: {
            import: () =>
                import('./frontend/scenes/ErrorTrackingFingerprintsScene/ErrorTrackingIssueFingerprintsScene'),
            projectBased: true,
            name: 'Error tracking issue fingerprints',
        },
    },
    routes: {
        '/error_tracking': ['ErrorTracking', 'errorTracking'],
        '/error_tracking/:id': ['ErrorTrackingIssue', 'errorTrackingIssue'],
        '/error_tracking/:id/fingerprints': ['ErrorTrackingIssueFingerprints', 'errorTrackingIssueFingerprints'],
        '/error_tracking/alerts/:id': ['HogFunction', 'errorTrackingAlert'],
        '/error_tracking/alerts/new/:templateId': ['HogFunction', 'errorTrackingAlertNew'],
    },
    redirects: {
        '/error_tracking/configuration': (_params, searchParams, hashParams) => {
            const { tab, ...restSearchParams } = searchParams
            return combineUrl(
                '/error_tracking',
                { ...restSearchParams, activeTab: 'configuration' },
                { ...hashParams, ...(tab ? { selectedSetting: tab } : {}) }
            ).url
        },
    },
    urls: {
        errorTracking: (params = {}): string => combineUrl('/error_tracking', params).url,
        errorTrackingConfiguration: (params = {}): string =>
            combineUrl('/error_tracking', { ...params, activeTab: 'configuration' }).url,
        errorTrackingIssue: (
            id: string,
            params: {
                timestamp?: string
                fingerprint?: string
                searchQuery?: string
                dateRange?: DateRange
                filterGroup?: UniversalFiltersGroup
            } = {}
        ): string => combineUrl(`/error_tracking/${id}`, params).url,
        errorTrackingIssueFingerprints: (id: string): string => `/error_tracking/${id}/fingerprints`,
        errorTrackingAlert: (id: string): string => `/error_tracking/alerts/${id}`,
        errorTrackingAlertNew: (templateId: string): string => `/error_tracking/alerts/new/${templateId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Error tracking',
            intents: [ProductKey.ERROR_TRACKING],
            category: ProductItemCategory.BEHAVIOR,
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
