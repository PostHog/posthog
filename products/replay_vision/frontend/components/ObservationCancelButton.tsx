import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlLevel } from '~/types'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'

/** Stops a pending or running scan. Renders nothing once the scan has settled. */
export function ObservationCancelButton({
    status,
    onCancel,
    loading = false,
    userAccessLevel,
    iconOnly = false,
    dataAttr,
}: {
    status: ReplayObservationApi['status']
    onCancel: () => void
    loading?: boolean
    userAccessLevel?: AccessControlLevel | null
    iconOnly?: boolean
    dataAttr: string
}): JSX.Element | null {
    if (status !== 'pending' && status !== 'running') {
        return null
    }
    return (
        <LemonButton
            size="xsmall"
            type="tertiary"
            icon={<IconX />}
            onClick={onCancel}
            loading={loading}
            disabledReason={getReplayVisionEditDisabledReason(userAccessLevel)}
            tooltip="Stop this scan. A canceled scan uses no credits."
            data-attr={dataAttr}
        >
            {iconOnly ? undefined : 'Cancel'}
        </LemonButton>
    )
}
