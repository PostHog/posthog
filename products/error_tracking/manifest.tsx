import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { DateRange, FileSystemIconType, ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import type { Params } from '../../frontend/src/scenes/sceneTypes'
import { FileSystemIconColor, ProductManifest, UniversalFiltersGroup } from '../../frontend/src/types'

// The configuration pages (symbol sets, alerting, and so on) used to be their own routes.
// They are now tabs in the configuration settings panel, so map each old path slug to its
// current setting id. Both underscore and hyphen slug spellings appear in old links.
const LEGACY_SETTING_SLUGS: Record<string, string> = {
    alerting: 'error-tracking-alerting',
    'assignment-rules': 'error-tracking-auto-assignment',
    'exception-autocapture': 'error-tracking-exception-autocapture',
    'grouping-rules': 'error-tracking-custom-grouping',
    'rate-limit': 'error-tracking-rate-limits',
    releases: 'error-tracking-releases',
    'spike-detection': 'error-tracking-spike-detection',
    'suppression-rules': 'error-tracking-suppression-rules',
    'symbol-sets': 'error-tracking-symbol-sets',
}

function resolveSettingSlug(slug: string | undefined): string | undefined {
    if (!slug) {
        return undefined
    }
    const normalized = slug.replace(/_/g, '-')
    return LEGACY_SETTING_SLUGS[normalized] ?? slug
}

function configurationRedirect(settingId: string | undefined, searchParams: Params, hashParams: Params): string {
    const { tab, ...restSearchParams } = searchParams
    return combineUrl(
        '/error_tracking',
        { ...restSearchParams, activeTab: 'configuration' },
        { ...hashParams, ...(settingId ? { selectedSetting: settingId } : {}) }
    ).url
}

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
        ErrorTrackingFingerprint: {
            import: () => import('./frontend/scenes/ErrorTrackingFingerprintScene/ErrorTrackingFingerprintScene'),
            projectBased: true,
            name: 'Error tracking fingerprint',
        },
    },
    routes: {
        '/error_tracking': ['ErrorTracking', 'errorTracking'],
        '/error_tracking/fingerprint/*': ['ErrorTrackingFingerprint', 'errorTrackingFingerprint'],
        '/error_tracking/alerts/new/:templateId': ['HogFunction', 'errorTrackingAlertNew'],
        '/error_tracking/alerts/:id': ['HogFunction', 'errorTrackingAlert'],
        '/error_tracking/:id': ['ErrorTrackingIssue', 'errorTrackingIssue'],
        '/error_tracking/:id/fingerprints': ['ErrorTrackingIssueFingerprints', 'errorTrackingIssueFingerprints'],
    },
    redirects: {
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
                utm_source?: string
                utm_campaign?: string
                utm_medium?: string
            } = {}
        ): string => combineUrl(`/error_tracking/${id}`, params).url,
        errorTrackingIssueFingerprints: (id: string): string => `/error_tracking/${id}/fingerprints`,
        errorTrackingFingerprint: (
            fingerprint: string,
            params: {
                timestamp?: string
            } = {}
        ): string => combineUrl(`/error_tracking/fingerprint/${encodeURIComponent(fingerprint)}`, params).url,
        errorTrackingAlert: (id: string): string => `/error_tracking/alerts/${id}`,
        errorTrackingAlertNew: (templateId: string): string => `/error_tracking/alerts/new/${templateId}`,
    },
    fileSystemTypes: {},
    treeItemsNew: [],
    treeItemsProducts: [
        {
            path: 'Error tracking',
            intents: [ProductKey.ERROR_TRACKING],
            category: ProductItemCategory.APP_MONITORING,
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
