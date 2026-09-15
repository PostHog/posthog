import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

/** Sidebar + deep-link id for the Logs → Configuration → Retention setting. */
export const LOGS_RETENTION_SETTING_ID = 'logs-retention' as const

/** Logs scene, Configuration tab, environment logs section, Retention item (query + hash for deep links). */
export function logsRetentionSettingsUrl(): string {
    return combineUrl(
        urls.logs(),
        {
            activeTab: 'configuration',
            section: 'environment-logs',
            setting: LOGS_RETENTION_SETTING_ID,
        },
        { selectedSetting: LOGS_RETENTION_SETTING_ID }
    ).url
}
