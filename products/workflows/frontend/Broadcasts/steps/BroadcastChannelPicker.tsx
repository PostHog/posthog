import { useActions, useValues } from 'kea'

import { IconBell, IconCheckCircle, IconLetter } from '@posthog/icons'
import { LemonButton, LemonDialog, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { BroadcastChannel } from '../broadcastsLogic'
import { broadcastWizardLogic, hasMessageContent } from '../broadcastWizardLogic'

const CHANNELS: { channel: BroadcastChannel; label: string; description: string; icon: JSX.Element }[] = [
    { channel: 'email', label: 'Email', description: "Lands in each person's inbox", icon: <IconLetter /> },
    { channel: 'push', label: 'Push', description: "Shows on each person's phone", icon: <IconBell /> },
]

const NO_PUSH_REASON = "Your project doesn't have push set up yet"

export function BroadcastChannelPicker(): JSX.Element {
    const { channel, email, push, hasPushChannels, integrationsLoading } = useValues(broadcastWizardLogic)
    const { setChannel } = useActions(broadcastWizardLogic)

    const pick = (next: BroadcastChannel): void => {
        if (next === channel) {
            return
        }
        if (!hasMessageContent(channel, email, push)) {
            setChannel(next)
            return
        }
        LemonDialog.open({
            title: `Switch to ${next === 'push' ? 'push' : 'email'}?`,
            description: `A broadcast sends on one channel, so the ${
                channel === 'email' ? 'email' : 'push notification'
            } you wrote is removed from this broadcast.`,
            primaryButton: {
                children: 'Switch',
                status: 'danger',
                onClick: () => setChannel(next),
                'data-attr': 'broadcast-channel-switch-confirm',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const pushUnavailable = !integrationsLoading && !hasPushChannels && channel !== 'push'

    return (
        <div className="flex flex-col gap-1">
            <span className="font-semibold">Channel</span>
            <div className="grid grid-cols-1 gap-2 @md:grid-cols-2">
                {CHANNELS.map((option) => (
                    <LemonButton
                        key={option.channel}
                        type="secondary"
                        active={channel === option.channel}
                        icon={option.icon}
                        onClick={() => pick(option.channel)}
                        disabledReason={option.channel === 'push' && pushUnavailable ? NO_PUSH_REASON : undefined}
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
            {pushUnavailable ? (
                <span className="text-xs text-secondary">
                    {NO_PUSH_REASON}.{' '}
                    <Link to={urls.workflows('channels')} target="_blank" data-attr="broadcast-channel-set-up-push">
                        Set it up
                    </Link>
                </span>
            ) : null}
        </div>
    )
}
