import { useActions, useValues } from 'kea'

import { IconBell, IconLetter } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { broadcastWizardLogic } from '../broadcastWizardLogic'

/** A late change of channel on the Content step. The channel is picked first, on the Recipients step. */
export function BroadcastChannelSwitch(): JSX.Element {
    const { channel, pushUnavailableReason } = useValues(broadcastWizardLogic)
    const { requestChannel } = useActions(broadcastWizardLogic)

    const next = channel === 'push' ? 'email' : 'push'
    return (
        <LemonButton
            type="tertiary"
            size="small"
            icon={next === 'push' ? <IconBell /> : <IconLetter />}
            onClick={() => requestChannel(next)}
            disabledReason={next === 'push' ? pushUnavailableReason : undefined}
            data-attr={`broadcast-channel-switch-${next}`}
        >
            {next === 'push' ? 'Send as push instead' : 'Send as email instead'}
        </LemonButton>
    )
}
