import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AccessControlLevel } from '~/types'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { observationRetryOffer } from '../replay_scanners/types'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'

/** Renders nothing when a retry isn't offered for the observation's status and kind (see `observationRetryOffer`). */
export function QuillObservationRetryButton({
    status,
    errorReason,
    onRetry,
    loading = false,
    userAccessLevel,
    emphasis = 'outline',
    size = 'xs',
    iconOnly = false,
    dataAttr,
}: {
    status: ReplayObservationApi['status']
    errorReason: string
    onRetry: () => void
    loading?: boolean
    userAccessLevel?: AccessControlLevel | null
    emphasis?: 'primary' | 'outline'
    size?: 'xs' | 'sm'
    iconOnly?: boolean
    dataAttr: string
}): JSX.Element | null {
    const { show, worthwhile, hint } = observationRetryOffer(status, errorReason)
    if (!show) {
        return null
    }
    return (
        <Button
            size={iconOnly ? (size === 'xs' ? 'icon-xs' : 'icon-sm') : size}
            variant={worthwhile ? emphasis : 'outline'}
            onClick={onRetry}
            loading={loading}
            disabledReason={getReplayVisionEditDisabledReason(userAccessLevel)}
            tooltip={hint ?? 'Retry scan'}
            aria-label={iconOnly ? 'Retry scan' : undefined}
            data-attr={dataAttr}
        >
            <IconRefresh />
            {iconOnly ? null : 'Retry scan'}
        </Button>
    )
}
