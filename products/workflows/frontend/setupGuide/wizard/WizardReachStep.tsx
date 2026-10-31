import { useActions, useValues } from 'kea'

import { IconLetter, IconPhone } from '@posthog/icons'
import { LemonCheckbox } from '@posthog/lemon-ui'

import { workflowsSetupGuideLogic } from '../workflowsSetupGuideLogic'
import { REACH_CHANNELS, ReachChannel } from './onboardingWizardSteps'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

const REACH_OPTIONS: Record<ReachChannel, { icon: JSX.Element; title: string; description: string; needs: string }> = {
    email: {
        icon: <IconLetter />,
        title: 'Email',
        description: 'Onboarding, lifecycle and transactional email from your own domain.',
        needs: 'You need access to the DNS settings of a domain you own.',
    },
    push: {
        icon: <IconPhone />,
        title: 'Push notifications',
        description: 'Notifications on the phones of people who use your iOS or Android app.',
        needs: 'You need Firebase or Apple push credentials and the PostHog SDK in your app.',
    },
}

export function WizardReachStep(): JSX.Element {
    const { reachChannels } = useValues(workflowsOnboardingWizardLogic)
    const { setReachChannels } = useActions(workflowsSetupGuideLogic)
    const selected = reachChannels ?? []

    const toggle = (channel: ReachChannel, checked: boolean): void => {
        setReachChannels(REACH_CHANNELS.filter((option) => (option === channel ? checked : selected.includes(option))))
    }

    return (
        <div className="@container flex flex-col gap-3">
            <div className="grid grid-cols-1 gap-3 @2xl:grid-cols-2">
                {REACH_CHANNELS.map((channel) => {
                    const option = REACH_OPTIONS[channel]
                    return (
                        <LemonCheckbox
                            key={channel}
                            bordered
                            fullWidth
                            className="h-full"
                            labelClassName="h-full items-start py-2"
                            checked={selected.includes(channel)}
                            onChange={(checked) => toggle(channel, checked)}
                            data-attr={`workflows-onboarding-wizard-reach-${channel}`}
                            label={
                                <span className="flex flex-col gap-1">
                                    <span className="flex items-center gap-2 font-semibold">
                                        <span className="text-lg flex">{option.icon}</span>
                                        {option.title}
                                    </span>
                                    <span className="text-secondary font-normal">{option.description}</span>
                                    <span className="text-tertiary text-xs font-normal">{option.needs}</span>
                                </span>
                            }
                        />
                    )
                })}
            </div>
            <p className="mb-0 text-secondary text-sm">
                SMS and Slack are in Messaging once setup is done. You can add any channel later.
            </p>
        </div>
    )
}
