import { useValues } from 'kea'

import { IconLetter, IconX } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { PLACEMENTS } from '../../mcp/messagingPlacements'
import { useMessagingCta } from './useMessagingCta'

type SendFromCodePlacementKey = Extract<(typeof PLACEMENTS)[number], { destination: 'send_from_code' }>['key']

export interface MessagingCtaChipProps {
    placement: SendFromCodePlacementKey
    disabledReason?: string | null
}

export function MessagingCtaChip(props: MessagingCtaChipProps): JSX.Element | null {
    const { user } = useValues(userLogic)
    return user ? <MessagingCtaChipForViewer {...props} viewerId={user.uuid} /> : null
}

function MessagingCtaChipForViewer({
    placement,
    disabledReason,
    viewerId,
}: MessagingCtaChipProps & { viewerId: string }): JSX.Element | null {
    const cta = useMessagingCta(placement, viewerId)
    if (!cta) {
        return null
    }
    return (
        <LemonTag
            type="muted"
            size="small"
            icon={<IconLetter />}
            className="min-w-0 max-w-full"
            data-attr={`messaging-cta-chip-${cta.placement.key}`}
        >
            <Tooltip title={disabledReason || cta.copy.description}>
                {disabledReason ? (
                    <span tabIndex={0} className="min-w-0 truncate">
                        {cta.copy.label}
                    </span>
                ) : (
                    <Link
                        to={urls.transactionalNew()}
                        onClickCapture={cta.onClick}
                        onAuxClick={(event) => event.button === 1 && cta.onClick()}
                        subtle
                        className="min-w-0 truncate"
                    >
                        {cta.copy.label}
                    </Link>
                )}
            </Tooltip>
            {cta.placement.dismissible && (
                <LemonButton
                    icon={<IconX className="h-3.5 w-3.5" />}
                    size="xsmall"
                    className="LemonTag__right-button"
                    aria-label="Hide for 90 days"
                    tooltip="Hide for 90 days"
                    onClick={cta.onDismiss}
                />
            )}
        </LemonTag>
    )
}
