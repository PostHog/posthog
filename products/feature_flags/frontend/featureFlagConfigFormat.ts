import { isApprovalRequiredError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { FeatureFlagConfig, FeatureFlagFilters, FeatureFlagRulesV2Config } from '~/types'

export type FeatureFlagConfigFormat = 'v1' | 'v2' | 'unsupported'

export const UNSUPPORTED_CONFIG_DISABLED_REASON =
    'This flag is stored in a configuration version this page cannot change.'
export const ARCHIVE_UNAVAILABLE_DISABLED_REASON = 'Archiving is not available for this flag yet.'
export const RESTORE_UNAVAILABLE_DISABLED_REASON = 'Restoring is not available for this flag yet.'
export const STALE_ROW_VERSION_RELOADED_MESSAGE = 'This flag changed elsewhere and has been reloaded.'

/** Mirrors the server's detector: no `version` or `1` is v1, `2` is v2, anything else is unsupported here. */
export function featureFlagConfigFormat(filters: FeatureFlagConfig | null | undefined): FeatureFlagConfigFormat {
    const version = filters?.version
    if (version === undefined || version === 1) {
        return 'v1'
    }
    if (version === 2) {
        return 'v2'
    }
    return 'unsupported'
}

export function isV1FeatureFlagConfig(filters: FeatureFlagConfig): filters is FeatureFlagFilters {
    return featureFlagConfigFormat(filters) === 'v1'
}

export function isRulesV2FeatureFlagConfig(filters: FeatureFlagConfig): filters is FeatureFlagRulesV2Config {
    return featureFlagConfigFormat(filters) === 'v2'
}

/** The server refuses `archived` on every config version but v1. */
export function canArchiveFeatureFlag(filters: FeatureFlagConfig | null | undefined): boolean {
    return featureFlagConfigFormat(filters) === 'v1'
}

/** The server refuses `deleted: false` on every config version but v1. */
export function canRestoreFeatureFlag(filters: FeatureFlagConfig | null | undefined): boolean {
    return featureFlagConfigFormat(filters) === 'v1'
}

/**
 * A write to a row in another config version must carry the row version. For a v1 row this returns
 * `{}`, so the write sends no version and the server applies it without a version check.
 */
export function rowVersionToken(
    flag: { filters?: FeatureFlagConfig | null; version?: number | null } | null | undefined
): { version?: number } {
    return !flag || featureFlagConfigFormat(flag.filters) === 'v1' || flag.version == null
        ? {}
        : { version: flag.version }
}

export function isStaleRowVersionError(token: { version?: number }, error: any): boolean {
    return token.version !== undefined && error?.status === 409 && !isApprovalRequiredError(error)
}

// The conflicting write may have replaced the whole document, so a stale row version reloads the flag.
export function reloadIfStaleRowVersion(token: { version?: number }, error: any, reload: () => void): boolean {
    if (!isStaleRowVersionError(token, error)) {
        return false
    }
    lemonToast.error(error?.detail || STALE_ROW_VERSION_RELOADED_MESSAGE)
    reload()
    return true
}

/**
 * The `deleteWithUndo` options for a flag. A row in another config version refuses `id`, so the body is `deleted`
 * and the row version only, and there is no Undo for a flag the server will not restore.
 */
export function featureFlagDeleteOptions(
    flag: { filters?: FeatureFlagConfig | null; version?: number | null },
    reload: () => void
): { payload: { version?: number }; undoable: boolean; onError: (error: any) => boolean } {
    const versioned = rowVersionToken(flag)
    return {
        payload: versioned,
        undoable: canRestoreFeatureFlag(flag.filters),
        onError: (error) => reloadIfStaleRowVersion(versioned, error, reload),
    }
}

export function featureFlagConfigFormatLabel(filters: FeatureFlagConfig | null | undefined): string {
    const version = filters?.version
    switch (featureFlagConfigFormat(filters)) {
        case 'v1':
            return 'Config v1'
        case 'v2':
            return 'Rules v2'
        default:
            return typeof version === 'number' ? `Config v${version} (unsupported)` : 'Unsupported config'
    }
}
