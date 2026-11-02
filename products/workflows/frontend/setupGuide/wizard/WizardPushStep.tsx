import { useActions, useValues } from 'kea'

import { IconAndroid, IconApple, IconCheckCircle } from '@posthog/icons'
import { LemonSegmentedButton, Link, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { SetupTaskId } from 'lib/components/ProductSetup'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { ChannelCatalogCard } from '../../Channels/ChannelCatalogCard'
import { ChannelSetupModal } from '../../Channels/ChannelSetupModal'
import { summarizeChannel } from '../../Channels/channelSummary'
import { PushPlatform, pushDeviceCheckLogic } from './pushDeviceCheckLogic'

const PLATFORMS: Record<PushPlatform, { label: string; provider: 'apns' | 'firebase'; minVersion: string }> = {
    ios: { label: 'iOS', provider: 'apns', minVersion: '3.69.0' },
    android: { label: 'Android', provider: 'firebase', minVersion: '3.58.0' },
}

function sdkSnippet(platform: PushPlatform, token: string, host: string, appId: string | undefined): string {
    if (platform === 'ios') {
        return `let config = PostHogConfig(apiKey: "${token}", host: "${host}")
config.capturePushNotificationSubscriptions = true // on by default
PostHogSDK.shared.setup(config)

// Ask for permission. The SDK registers the device token for you.
UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, _ in
    if granted {
        DispatchQueue.main.async { UIApplication.shared.registerForRemoteNotifications() }
    }
}`
    }
    return `val config = PostHogAndroidConfig(apiKey = "${token}", host = "${host}").apply {
    capturePushNotificationSubscriptions = true // on by default, needs firebase-messaging
}
PostHogAndroid.setup(this, config)

// In your FirebaseMessagingService, so a refreshed token registers right away
override fun onNewToken(token: String) {
    PostHog.registerPushNotificationToken(token, "${appId ?? '<firebase project id>'}")
}`
}

function StepTitle({ index, done, children }: { index: number; done: boolean; children: string }): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            {done ? (
                <IconCheckCircle className="text-success text-lg shrink-0" />
            ) : (
                <span className="flex items-center justify-center size-5 rounded-full border text-xs font-semibold shrink-0">
                    {index}
                </span>
            )}
            <span className="font-semibold">{children}</span>
        </div>
    )
}

export function WizardPushStep(): JSX.Element {
    const { integrations, setupModalOpen, setupModalType, selectedIntegration } = useValues(integrationsLogic)
    const { closeSetupModal, markTaskAsCompleted } = useActions(integrationsLogic)
    const { platform, providerConnected, appId, appIds, registeredDeviceCount, deviceRegistered } =
        useValues(pushDeviceCheckLogic)
    const { setPlatform } = useActions(pushDeviceCheckLogic)
    const { currentTeam } = useValues(teamLogic)
    const { label, provider, minVersion } = PLATFORMS[platform]

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
            <div className="flex flex-col gap-6" data-attr="workflows-onboarding-wizard-push">
                <div className="flex flex-wrap items-center gap-3">
                    <span className="font-semibold">Your app runs on</span>
                    <LemonSegmentedButton
                        value={platform}
                        onChange={(value) => setPlatform(value)}
                        options={[
                            { value: 'ios', label: 'iOS', icon: <IconApple />, 'data-attr': 'push-platform-ios' },
                            {
                                value: 'android',
                                label: 'Android',
                                icon: <IconAndroid />,
                                'data-attr': 'push-platform-android',
                            },
                        ]}
                        size="small"
                    />
                    <span className="text-secondary text-sm">On both? Set up one now and the other after.</span>
                </div>

                <div className="flex flex-col gap-2">
                    <StepTitle index={1} done={providerConnected}>
                        {`Connect ${provider === 'apns' ? 'Apple Push Notifications' : 'Firebase Cloud Messaging'}`}
                    </StepTitle>
                    <div className="ps-7">
                        <ChannelCatalogCard
                            channel={summarizeChannel(provider, integrations ?? [])}
                            disabledReason={null}
                        />
                    </div>
                </div>

                <div className="flex flex-col gap-2">
                    <StepTitle index={2} done={deviceRegistered}>
                        Turn on push in the PostHog SDK
                    </StepTitle>
                    <div className="ps-7 flex flex-col gap-2">
                        <span className="text-secondary text-sm">
                            {`Use the ${label} SDK ${minVersion} or later. Your app still needs push set up, and it must ask people for permission.`}
                        </span>
                        <CodeSnippet language={platform === 'ios' ? Language.Swift : Language.Kotlin} wrap>
                            {sdkSnippet(
                                platform,
                                currentTeam?.api_token ?? '<project token>',
                                apiHostOrigin(),
                                appId ?? undefined
                            )}
                        </CodeSnippet>
                        <span className="text-secondary text-sm">
                            Using React Native or Flutter?{' '}
                            <Link
                                to="https://posthog.com/docs/workflows/push-notifications"
                                target="_blank"
                                data-attr="workflows-onboarding-wizard-push-docs"
                            >
                                Read the push setup guide
                            </Link>
                            .
                        </span>
                    </div>
                </div>

                <div className="flex flex-col gap-2">
                    <StepTitle index={3} done={deviceRegistered}>
                        Open your app on a device
                    </StepTitle>
                    <div className="ps-7 text-sm" data-attr="workflows-onboarding-wizard-push-device-status">
                        {!providerConnected ? (
                            <span className="text-secondary">
                                {`Devices can register once ${provider === 'apns' ? 'Apple Push Notifications is' : 'Firebase is'} connected.`}
                            </span>
                        ) : deviceRegistered ? (
                            <span>
                                <strong>
                                    {registeredDeviceCount === 1 ? '1 person' : `${registeredDeviceCount} people`}
                                </strong>{' '}
                                can get push notifications from this app. You're ready to send.
                            </span>
                        ) : (
                            <span className="flex items-center gap-2 text-secondary">
                                <Spinner textColored />
                                {`Waiting for a device${appIds.length > 1 ? ` on ${appId}` : ''}. Open your app and allow notifications. You can also continue and come back later.`}
                            </span>
                        )}
                    </div>
                </div>
            </div>
        </>
    )
}
