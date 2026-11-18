import type { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { FeatureFlagType } from '~/types'

import { featureFlagConfigFormat } from '../featureFlagConfigFormat'

/** The flag version an activity log entry produced, or null when the entry did not produce one. */
export function flagVersionOfActivity(logItem: ActivityLogItem | undefined): number | null {
    if (!logItem || logItem.scope !== 'FeatureFlag') {
        return null
    }
    // A flag is created at version 1 and the creation entry carries no changes.
    if (logItem.activity === 'created') {
        return 1
    }
    const versionChange = (logItem.detail.changes || []).find((change) => change.field === 'version')
    return typeof versionChange?.after === 'number' ? versionChange.after : null
}

type RestorableFlag = Pick<
    FeatureFlagType,
    'version' | 'deleted' | 'archived' | 'has_encrypted_payloads' | 'can_edit' | 'filters'
>

/** Why a past version of this flag cannot be restored, or null when it can. Mirrors the server's refusals. */
export function restoreVersionDisabledReason(flag: RestorableFlag, version: number): string | null {
    if (!flag.can_edit) {
        return "You don't have permission to edit this flag."
    }
    if (version === (flag.version ?? 0)) {
        return 'This is the current version.'
    }
    if (flag.deleted) {
        return 'Restore this flag to restore a past version.'
    }
    if (flag.archived) {
        return 'Unarchive this flag to restore a past version.'
    }
    if (flag.has_encrypted_payloads) {
        return "Past versions of a flag with encrypted payloads can't be restored."
    }
    if (featureFlagConfigFormat(flag.filters) !== 'v1') {
        return "Past versions of this flag can't be restored yet."
    }
    return null
}
