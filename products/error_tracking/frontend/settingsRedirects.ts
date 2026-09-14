import { combineUrl } from 'kea-router'

import type { Params } from 'scenes/sceneTypes'

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

export function resolveSettingSlug(slug: string | undefined): string | undefined {
    if (!slug) {
        return undefined
    }
    const normalized = slug.replace(/_/g, '-')
    return LEGACY_SETTING_SLUGS[normalized] ?? slug
}

export function configurationRedirect(settingId: string | undefined, searchParams: Params, hashParams: Params): string {
    const { tab, ...restSearchParams } = searchParams
    return combineUrl(
        '/error_tracking',
        { ...restSearchParams, activeTab: 'configuration' },
        { ...hashParams, ...(settingId ? { selectedSetting: settingId } : {}) }
    ).url
}
