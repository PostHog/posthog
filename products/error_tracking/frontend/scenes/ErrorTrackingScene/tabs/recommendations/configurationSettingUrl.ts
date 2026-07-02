import { combineUrl } from 'kea-router'

import { SettingId } from 'scenes/settings/types'
import { urls } from 'scenes/urls'

/** Error tracking scene, Configuration tab, deep-linked to a specific setting. */
export function errorTrackingConfigurationSettingUrl(settingId: SettingId): string {
    return combineUrl(urls.errorTracking(), { activeTab: 'configuration' }, { selectedSetting: settingId }).url
}

/**
 * Error tracking Configuration tab, deep-linked to the Symbol sets panel. When a symbol set
 * reference is provided the panel's search is pre-filled with it, so a user jumping from an
 * unresolved / missing-context stack frame lands directly on the set behind that frame.
 */
export function errorTrackingSymbolSetUrl(symbolSetRef?: string | null): string {
    const base = errorTrackingConfigurationSettingUrl('error-tracking-symbol-sets')
    return symbolSetRef ? combineUrl(base, { symbolSetRef }).url : base
}
