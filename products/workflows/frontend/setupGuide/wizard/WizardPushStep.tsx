import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconBell } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { ChannelCatalogCard } from '../../Channels/ChannelCatalogCard'
import { ChannelSetupModal } from '../../Channels/ChannelSetupModal'
import { summarizeChannel } from '../../Channels/channelSummary'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

const SDK_REQUIREMENTS = [
    { platform: 'iOS', version: '3.69.0' },
    { platform: 'Android', version: '3.58.0' },
    { platform: 'React Native', version: '4.62.0, with @posthog/react-native-plugin' },
    { platform: 'Flutter', version: '5.35.0' },
]

export function WizardPushStep(): JSX.Element {
    const { integrations, setupModalOpen, setupModalType, selectedIntegration } = useValues(integrationsLogic)
    const { closeSetupModal, markTaskAsCompleted } = useActions(integrationsLogic)
    const { stepDone } = useValues(workflowsOnboardingWizardLogic)
    const { next } = useActions(workflowsOnboardingWizardLogic)
    const [settingUpPush, setSettingUpPush] = useState(false)

    const answer = (wantsPush: boolean): void => {
        // pinned: analytics event name - renaming breaks dashboards
        posthog.capture('workflows onboarding wizard push answered', { wants_push: wantsPush })
        if (wantsPush) {
            setSettingUpPush(true)
        } else {
            next()
        }
    }

    if (!settingUpPush && !stepDone?.push) {
        return (
            <div className="flex flex-col items-center gap-3 py-6 text-center">
                <div className="flex items-center justify-center size-12 rounded-full bg-surface-secondary">
                    <IconBell className="size-6" />
                </div>
                <p className="mb-0 max-w-md text-secondary">
                    If you have a mobile app, workflows can send push notifications to Android and iOS devices.
                </p>
                <div className="flex flex-wrap justify-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => answer(false)}
                        data-attr="workflows-onboarding-wizard-push-no"
                    >
                        No, just email
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => answer(true)}
                        data-attr="workflows-onboarding-wizard-push-yes"
                    >
                        Yes, set up push
                    </LemonButton>
                </div>
            </div>
        )
    }

    return (
        <>
            <ChannelSetupModal
                isOpen={setupModalOpen}
                channelType={setupModalType}
                integration={selectedIntegration || undefined}
                onClose={closeSetupModal}
                onComplete={() => {
                    markTaskAsCompleted(SetupTaskId.SetUpFirstWorkflowChannel)
                    closeSetupModal()
                }}
            />
            <div className="@container flex flex-col gap-4">
                <p className="mb-0 text-secondary">
                    Connect the platforms your app runs on. You can connect one now and the other later.
                </p>
                <div className="grid grid-cols-1 gap-3 @2xl:grid-cols-2">
                    <ChannelCatalogCard
                        channel={summarizeChannel('firebase', integrations ?? [])}
                        disabledReason={null}
                    />
                    <ChannelCatalogCard channel={summarizeChannel('apns', integrations ?? [])} disabledReason={null} />
                </div>
                <div className="flex flex-col gap-2 rounded border p-4">
                    <span className="font-semibold">Add PostHog to your app</span>
                    <span className="text-secondary text-sm">
                        The PostHog SDK registers each device for push on its own. Your app still needs push set up, and
                        it must ask people for permission to send notifications. Use at least these SDK versions:
                    </span>
                    <ul className="mb-0 list-disc ps-5 text-sm">
                        {SDK_REQUIREMENTS.map(({ platform, version }) => (
                            <li key={platform}>
                                {platform}: {version}
                            </li>
                        ))}
                    </ul>
                    <Link
                        to="https://posthog.com/docs/workflows/push-notifications"
                        target="_blank"
                        className="text-sm"
                        data-attr="workflows-onboarding-wizard-push-docs"
                    >
                        Read the push setup guide
                    </Link>
                </div>
            </div>
        </>
    )
}
