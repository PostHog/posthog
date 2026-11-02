import { useActions, useValues } from 'kea'

import { IconBell, IconCheckCircle, IconLetter } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

import { BroadcastChannel } from '../broadcastsLogic'
import {
    NO_PUSH_CHANNELS_REASON,
    PUSH_CHANNELS_LOAD_FAILED_REASON,
    broadcastWizardLogic,
} from '../broadcastWizardLogic'

const CHANNELS: { channel: BroadcastChannel; label: string; description: string; icon: JSX.Element }[] = [
    { channel: 'email', label: 'Email', description: "Lands in each person's inbox", icon: <IconLetter /> },
    { channel: 'push', label: 'Push', description: "Shows on each person's phone", icon: <IconBell /> },
]

export function BroadcastChannelPicker(): JSX.Element {
    const { channel, pushUnavailableReason } = useValues(broadcastWizardLogic)
    const { requestChannel } = useActions(broadcastWizardLogic)
    const { loadIntegrations } = useActions(integrationsLogic)

    const pushUnavailable = channel !== 'push' ? pushUnavailableReason : null

    return (
        <div className="flex flex-col gap-1">
            <span className="font-semibold">Send as</span>
            <div className="grid grid-cols-1 gap-2 @md:grid-cols-2">
                {CHANNELS.map((option) => (
                    <LemonButton
                        key={option.channel}
                        type="secondary"
                        active={channel === option.channel}
                        icon={option.icon}
                        onClick={() => requestChannel(option.channel)}
                        disabledReason={option.channel === 'push' ? pushUnavailable : undefined}
                        sideIcon={channel === option.channel ? <IconCheckCircle className="text-success" /> : null}
                        fullWidth
                        data-attr={`broadcast-channel-${option.channel}`}
                    >
                        <div className="flex flex-col items-start py-1">
                            <span className="font-semibold">{option.label}</span>
                            <span className="text-xs font-normal text-secondary">{option.description}</span>
                        </div>
                    </LemonButton>
                ))}
            </div>
            {pushUnavailable === PUSH_CHANNELS_LOAD_FAILED_REASON ? (
                <span className="text-xs text-warning">
                    {PUSH_CHANNELS_LOAD_FAILED_REASON}.{' '}
                    <Link onClick={() => loadIntegrations()} data-attr="broadcast-channel-reload-push">
                        Try again
                    </Link>
                </span>
            ) : pushUnavailable ? (
                <span className="text-xs text-secondary">
                    {NO_PUSH_CHANNELS_REASON}.{' '}
                    <Link to={urls.workflows('channels')} target="_blank" data-attr="broadcast-channel-set-up-push">
                        Set it up
                    </Link>
                </span>
            ) : null}
        </div>
    )
}
