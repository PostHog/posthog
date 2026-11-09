import { useActions, useValues } from 'kea'

import { IconUndo } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { featureFlagRestoreVersionLogic } from './featureFlagRestoreVersionLogic'
import { flagVersionOfActivity, restoreVersionDisabledReason } from './flagVersionRestore'

export interface FeatureFlagRestoreVersionButtonProps {
    flagId: number
    logItem: HumanizedActivityLogItem
}

export function FeatureFlagRestoreVersionButton({
    flagId,
    logItem,
}: FeatureFlagRestoreVersionButtonProps): JSX.Element | null {
    const logic = featureFlagRestoreVersionLogic({ flagId })
    const { busyVersion, featureFlag } = useValues(logic)
    const { restoreVersion } = useActions(logic)

    const version = flagVersionOfActivity(logItem.unprocessed)
    if (version === null) {
        return null
    }

    return (
        <LemonButton
            noPadding
            icon={<IconUndo />}
            onClick={() => restoreVersion(version)}
            loading={busyVersion === version}
            disabledReason={
                restoreVersionDisabledReason(featureFlag, version) ??
                (busyVersion !== null && busyVersion !== version ? 'Another restore is in progress.' : null)
            }
            tooltip={`Restore version ${version}`}
            aria-label={`Restore version ${version}`}
            data-attr="feature-flag-restore-version"
        />
    )
}
