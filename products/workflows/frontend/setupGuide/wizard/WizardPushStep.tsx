import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { ChannelCatalogCard } from '../../Channels/ChannelCatalogCard'
import { ChannelSetupModal } from '../../Channels/ChannelSetupModal'
import { summarizeChannel } from '../../Channels/channelSummary'

const SDK_REQUIREMENTS = [
    { platform: 'iOS', version: '3.69.0' },
    { platform: 'Android', version: '3.58.0' },
    { platform: 'React Native', version: '4.62.0, with @posthog/react-native-plugin' },
    { platform: 'Flutter', version: '5.35.0' },
]

export function WizardPushStep(): JSX.Element {
    const { integrations, setupModalOpen, setupModalType, selectedIntegration } = useValues(integrationsLogic)
    const { closeSetupModal, markTaskAsCompleted } = useActions(integrationsLogic)

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
