import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

/** Sidebar + deep-link id for the Logs → Configuration → Drop rules setting. */
export const LOGS_DROP_RULES_SETTING_ID = 'logs-drop-rules' as const

/** Logs scene, Configuration tab, environment logs section, Drop rules item (query + hash for deep links). */
export function logsDropRulesSettingsUrl(): string {
    return combineUrl(
        urls.logs(),
        {
            activeTab: 'configuration',
            section: 'environment-logs',
            setting: LOGS_DROP_RULES_SETTING_ID,
        },
        { selectedSetting: LOGS_DROP_RULES_SETTING_ID }
    ).url
}
