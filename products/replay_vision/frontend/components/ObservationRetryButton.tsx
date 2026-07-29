import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlLevel } from '~/types'

import { failureRetryGuidance, parseFailureReason } from '../replay_scanners/types'
import { getReplayVisionEditDisabledReason } from '../utils/accessControl'

/**
 * Retry control for a failed observation, shared by the dock card, the observations table, and the detail scene.
 *
 * Retry stays available for every failure kind, because the user can know things we don't (that they just rewrote the
 * scanner prompt, say). What varies per kind is how hard we push it: kinds that recover on their own keep the caller's
 * emphasis, and the rest drop to secondary and use the tooltip to say why a plain retry probably isn't the next step.
 */
export function ObservationRetryButton({
    errorReason,
    onRetry,
    loading = false,
    userAccessLevel,
    emphasis = 'secondary',
    size = 'xsmall',
    iconOnly = false,
    dataAttr,
}: {
    errorReason: string
    onRetry: () => void
    loading?: boolean
    userAccessLevel?: AccessControlLevel | null
    emphasis?: 'primary' | 'secondary'
    size?: 'xsmall' | 'small'
    iconOnly?: boolean
    dataAttr: string
}): JSX.Element {
    const { worthwhile, hint } = failureRetryGuidance(parseFailureReason(errorReason)?.kind ?? null)
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
