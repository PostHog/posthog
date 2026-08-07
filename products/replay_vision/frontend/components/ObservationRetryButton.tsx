import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlLevel } from '~/types'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { observationRetryOffer } from '../replay_scanners/types'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'

/**
 * Retry control for a terminal observation, shared by the dock card, the observations table, and the detail scene.
 *
 * Renders nothing when a retry isn't offered for the observation's status and kind (see `observationRetryOffer`).
 * Where it is offered, what varies per kind is how hard we push it: kinds that recover on their own keep the
 * caller's emphasis, and the rest drop to secondary and use the tooltip to say why a plain retry probably isn't
 * the next step.
 */
export function ObservationRetryButton({
    status,
    errorReason,
    onRetry,
    loading = false,
    userAccessLevel,
    emphasis = 'secondary',
    size = 'xsmall',
    iconOnly = false,
    dataAttr,
}: {
    status: ReplayObservationApi['status']
    errorReason: string
    onRetry: () => void
    loading?: boolean
    userAccessLevel?: AccessControlLevel | null
    emphasis?: 'primary' | 'secondary'
    size?: 'xsmall' | 'small'
    iconOnly?: boolean
    dataAttr: string
}): JSX.Element | null {
    const { show, worthwhile, hint } = observationRetryOffer(status, errorReason)
    if (!show) {
        return null
    }
    return (
        <LemonButton
            size={size}
            type={worthwhile ? emphasis : 'secondary'}
            icon={<IconRefresh />}
            onClick={onRetry}
            loading={loading}
            disabledReason={getReplayVisionEditDisabledReason(userAccessLevel)}
            tooltip={hint ?? 'Retry scan'}
            data-attr={dataAttr}
        >
            {iconOnly ? undefined : 'Retry scan'}
        </LemonButton>
    )
}
