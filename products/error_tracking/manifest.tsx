import { combineUrl, router } from 'kea-router'

import { urls } from 'scenes/urls'

import { DateRange, FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest, UniversalFiltersGroup } from '../../frontend/src/types'
import { configurationRedirect, resolveSettingSlug } from './frontend/settingsRedirects'

export const manifest: ProductManifest = {
    name: 'Error tracking',
    scenes: {
        ErrorTracking: {
            import: () => import('./frontend/scenes/ErrorTrackingScene/ErrorTrackingScene'),
            projectBased: true,
            name: 'Error tracking',
            iconType: 'error_tracking',
            description: 'Track and analyze your error tracking data to understand and fix issues.',
            docsHref: 'https://posthog.com/docs/error-tracking',
        },
        ErrorTrackingIssue: {
            import: () => import('./frontend/scenes/ErrorTrackingIssueScene/ErrorTrackingIssueScene'),
            projectBased: true,
            name: 'Error tracking issue',
            layout: 'app-raw',
        },
        ErrorTrackingFingerprint: {
            import: () => import('./frontend/scenes/ErrorTrackingFingerprintScene/ErrorTrackingFingerprintScene'),
            projectBased: true,
            name: 'Error tracking fingerprint',
        },
    },
    routes: {
        '/error-tracking': ['ErrorTracking', 'errorTracking'],
        '/error-tracking/fingerprint/*': ['ErrorTrackingFingerprint', 'errorTrackingFingerprint'],
        '/error-tracking/alerts/new/:templateId': ['HogFunction', 'errorTrackingAlertNew'],
        '/error-tracking/alerts/:id': ['HogFunction', 'errorTrackingAlert'],
        '/error-tracking/:id': ['ErrorTrackingIssue', 'errorTrackingIssue'],
    },
    redirects: {
        // The fingerprints scene became a modal on the issue page. Keep old links working.
        '/error_tracking/:id/fingerprints': (params) =>
            combineUrl(`/error-tracking/${params.id}`, { manageFingerprints: 'true' }).url,
        '/error_tracking/configuration': (_params, searchParams, hashParams) =>
            configurationRedirect(resolveSettingSlug(searchParams.tab), searchParams, hashParams),
        '/error_tracking/configuration/:tab': (params, searchParams, hashParams) =>
            configurationRedirect(resolveSettingSlug(params.tab), searchParams, hashParams),
        '/error_tracking/settings': (_params, searchParams, hashParams) =>
            configurationRedirect(resolveSettingSlug(searchParams.tab), searchParams, hashParams),
        '/error_tracking/settings/:tab': (params, searchParams, hashParams) =>
            configurationRedirect(resolveSettingSlug(params.tab), searchParams, hashParams),
        '/error_tracking/symbol_sets': (_params, searchParams, hashParams) =>
            configurationRedirect('error-tracking-symbol-sets', searchParams, hashParams),
        '/error_tracking/symbol-sets': (_params, searchParams, hashParams) =>
            configurationRedirect('error-tracking-symbol-sets', searchParams, hashParams),
        '/errors': (_params, searchParams, hashParams) => combineUrl('/error-tracking', searchParams, hashParams).url,
        '/error_tracking': (_params, searchParams, hashParams) =>
            combineUrl('/error-tracking', searchParams, hashParams).url,
        // kea-router decodeURI()s the wildcard capture, so rebuild the fingerprint from the raw pathname.
        '/error_tracking/fingerprint/*': (_params, searchParams, hashParams) => {
            const [, rawFingerprint = ''] =
                router.values.location.pathname.match(/\/error_tracking\/fingerprint\/([^/]+)\/?$/) ?? []
            return combineUrl(`/error-tracking/fingerprint/${rawFingerprint}`, searchParams, hashParams).url
        },
        '/error_tracking/alerts/new/:templateId': ({ templateId }, searchParams, hashParams) =>
            combineUrl(`/error-tracking/alerts/new/${templateId}`, searchParams, hashParams).url,
        '/error_tracking/alerts/:id': ({ id }, searchParams, hashParams) =>
            combineUrl(`/error-tracking/alerts/${id}`, searchParams, hashParams).url,
        '/error_tracking/:id': ({ id }, searchParams, hashParams) =>
            combineUrl(`/error-tracking/${id}`, searchParams, hashParams).url,
    },
    // Boot-time approximation of errorTrackingSetupLogic: a $exception definition
    // existing means issues exist. The in-scene check stays the source of truth
    // (it also reads the autocapture opt-in for the waiting state).
    setupProbe: {
        productKey: ProductKey.ERROR_TRACKING,
        hasDataEvents: ['$exception'],
    },
    urls: {
        errorTracking: (params = {}): string => combineUrl('/error-tracking', params).url,
        errorTrackingConfiguration: (params = {}): string =>
            combineUrl('/error-tracking', { ...params, activeTab: 'configuration' }).url,
        errorTrackingIssue: (
            id: string,
            params: {
                timestamp?: string
                fingerprint?: string
                searchQuery?: string
                dateRange?: DateRange
                filterGroup?: UniversalFiltersGroup
                utm_source?: string
                utm_campaign?: string
                utm_medium?: string
            } = {}
        ): string => combineUrl(`/error-tracking/${id}`, params).url,
        errorTrackingFingerprint: (
            fingerprint: string,
            params: {
                timestamp?: string
            } = {}
        ): string => combineUrl(`/error-tracking/fingerprint/${encodeURIComponent(fingerprint)}`, params).url,
        errorTrackingAlert: (id: string): string => `/error-tracking/alerts/${id}`,
        errorTrackingAlertNew: (templateId: string): string => `/error-tracking/alerts/new/${templateId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Error tracking',
            intents: [ProductKey.ERROR_TRACKING],
            category: ProductItemCategory.MONITORING,
            type: 'error_tracking',
            iconType: 'error_tracking' as FileSystemIconType,
            iconColor: [
                'var(--color-product-error-tracking-light)',
                'var(--color-product-error-tracking-dark)',
            ] as FileSystemIconColor,
            href: urls.errorTracking(),
            searchKeywords: ['exceptions', 'crashes', 'bugs', 'stack traces'],
            searchTabs: [{ name: 'Insights', href: urls.errorTracking({ activeTab: 'insights' }) }],
            sceneKey: 'ErrorTracking',
        },
    ],
}
