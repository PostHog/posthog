import { combineUrl } from 'kea-router'

import { SettingId } from 'scenes/settings/types'
import { urls } from 'scenes/urls'

/** Error tracking scene, Configuration tab, deep-linked to a specific setting. */
export function errorTrackingConfigurationSettingUrl(settingId: SettingId): string {
    return combineUrl(urls.errorTracking(), { activeTab: 'configuration' }, { selectedSetting: settingId }).url
}
