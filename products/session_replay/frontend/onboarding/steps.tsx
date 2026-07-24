import { useValues } from 'kea'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'
import { OnboardingProductConfiguration } from 'scenes/onboarding/legacy/OnboardingProductConfiguration'
import { type ProductConfigOption } from 'scenes/onboarding/legacy/onboardingProductConfigurationLogic'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import { SessionReplaySDKInstructions } from 'scenes/onboarding/legacy/sdks/session-replay/SessionReplaySDKInstructions'
import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { getMaskingConfigFromLevel, getMaskingLevelFromConfig } from 'scenes/session-recordings/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { AvailableFeature, OnboardingStepKey, type SessionRecordingMaskingLevel } from '~/types'

const SessionReplayConfigStep = (): JSX.Element => {
    const { hasAvailableFeature } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)

    const configOptions: ProductConfigOption[] = [
        {
            type: 'toggle',
            title: 'Capture console logs',
            description: `Capture console logs as a part of user session recordings.
                            Use the console logs alongside recordings to debug any issues with your app.`,
            teamProperty: 'capture_console_log_opt_in',
            value: currentTeam?.capture_console_log_opt_in ?? true,
            visible: true,
        },
        {
            type: 'toggle',
            title: 'Capture network performance',
            description: `Capture performance and network information alongside recordings. Use the
                            network requests and timings in the recording player to help you debug issues with your app.`,
            teamProperty: 'capture_performance_opt_in',
            value: currentTeam?.capture_performance_opt_in ?? true,
            visible: true,
        },
        {
            type: 'toggle',
            title: 'Record user sessions',
            description: 'Watch recordings of how users interact with your web app to see what can be improved.',
            teamProperty: 'session_recording_opt_in',
            value: true,
            visible: false,
        },
        {
            type: 'select',
            title: 'Masking',
            description: 'Choose the level of masking for your recordings.',
            value: getMaskingLevelFromConfig(currentTeam?.session_recording_masking_config ?? {}),
            teamProperty: 'session_recording_masking_config',
            onChange: (value: string | number | null) => {
                return {
                    session_recording_masking_config: getMaskingConfigFromLevel(value as SessionRecordingMaskingLevel),
                }
            },
            selectOptions: [
                { value: 'total-privacy', label: 'Total privacy (mask all text/images)' },
                { value: 'normal', label: 'Normal (mask inputs but not text/images)' },
                { value: 'free-love', label: 'Free love (mask only passwords)' },
            ],
            visible: true,
        },
    ]

    if (hasAvailableFeature(AvailableFeature.REPLAY_RECORDING_DURATION_MINIMUM)) {
        configOptions.push({
            type: 'select',
            title: 'Minimum session duration (seconds)',
            description: `Only record sessions that are longer than the specified duration.
                            Start with it low and increase it later if you're getting too many short sessions.`,
            teamProperty: 'session_recording_minimum_duration_milliseconds',
            value: currentTeam?.session_recording_minimum_duration_milliseconds || null,
            selectOptions: SESSION_REPLAY_MINIMUM_DURATION_OPTIONS,
            visible: true,
        })
    }

    return <OnboardingProductConfiguration options={configOptions} />
}

export const sessionReplayOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => {
        const installStep = {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.SESSION_REPLAY}`,
            productKey: ProductKey.SESSION_REPLAY,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            setupTaskId: SetupTaskId.SetupSessionRecordings,
            dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
            render: () => <OnboardingInstallStep sdkInstructionMap={SessionReplaySDKInstructions} />,
        }

        if (ctx.role === 'secondary') {
            return [installStep]
        }

        return [
            installStep,
            {
                id: `${OnboardingStepKey.PRODUCT_CONFIGURATION}:${ProductKey.SESSION_REPLAY}`,
                productKey: ProductKey.SESSION_REPLAY,
                stepKey: OnboardingStepKey.PRODUCT_CONFIGURATION,
                role: ctx.role,
                setupTaskId: SetupTaskId.ConfigureRecordingSettings,
                render: () => <SessionReplayConfigStep />,
            },
        ]
    },
    completeRedirectUrl: () => urls.replay(),
}
