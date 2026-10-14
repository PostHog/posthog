import type { WorkflowsConfig } from '~/types'

import { UTM_TAG_KEYS, type UtmTagKey, type UtmTagValues } from './UtmTagFields'

export interface TeamUtmDefaults {
    enabled: boolean
    params: UtmTagValues
}

/** Drops empty values and trims the rest, the same way the team API stores them. */
export function cleanUtmParams(params: UtmTagValues | null | undefined): UtmTagValues {
    const cleaned: UtmTagValues = {}
    for (const key of UTM_TAG_KEYS) {
        const value = params?.[key]?.trim()
        if (value) {
            cleaned[key] = value
        }
    }
    return cleaned
}

export function getTeamUtmDefaults(config: WorkflowsConfig | null | undefined): TeamUtmDefaults {
    return { enabled: config?.email_utm_tags_enabled === true, params: cleanUtmParams(config?.email_utm_params) }
}

export function newEmailUtmConfig(defaults: TeamUtmDefaults): {
    utm_tags_enabled: boolean
    utm_params: UtmTagValues
    utm_params_from_default: UtmTagKey[]
} {
    return {
        utm_tags_enabled: defaults.enabled,
        utm_params: { ...defaults.params },
        utm_params_from_default: [...UTM_TAG_KEYS],
    }
}

/**
 * Which keys still follow the team default after an edit. A key someone changed stops following it,
 * so applying new team defaults later leaves that value alone. Steps from before team defaults have
 * no list, and all their keys count as following.
 */
export function utmKeysFromDefaultAfterEdit(
    fromDefault: UtmTagKey[] | undefined,
    previous: UtmTagValues,
    next: UtmTagValues
): UtmTagKey[] {
    const following = fromDefault ?? [...UTM_TAG_KEYS]
    return following.filter((key) => (previous[key] ?? '') === (next[key] ?? ''))
}

export function matchesTeamUtmDefaults(params: UtmTagValues, defaults: TeamUtmDefaults): boolean {
    const cleaned = cleanUtmParams(params)
    return UTM_TAG_KEYS.every((key) => (cleaned[key] ?? '') === (defaults.params[key] ?? ''))
}
