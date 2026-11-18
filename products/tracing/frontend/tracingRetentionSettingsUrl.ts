import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

/** Sidebar + deep-link id for the Tracing → Configuration → Retention setting. */
export const TRACING_RETENTION_SETTING_ID = 'tracing-retention' as const

/** Tracing scene, Configuration tab, environment tracing section, Retention item. */
export function tracingRetentionSettingsUrl(): string {
    return combineUrl(
        urls.tracing(),
        {
            activeTab: 'configuration',
            section: 'environment-tracing',
            setting: TRACING_RETENTION_SETTING_ID,
        },
        { selectedSetting: TRACING_RETENTION_SETTING_ID }
    ).url
}
