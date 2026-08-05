import { useValues } from 'kea'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { OnboardingProductConfiguration } from 'scenes/onboarding/legacy/OnboardingProductConfiguration'
import { type ProductConfigOption } from 'scenes/onboarding/legacy/onboardingProductConfigurationLogic'
import { OnboardingSessionReplayConfiguration } from 'scenes/onboarding/legacy/OnboardingSessionReplayConfiguration'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import {
    ProductAnalyticsSDKInstructions,
    ProductAnalyticsSDKTagOverrides,
} from 'scenes/onboarding/legacy/sdks/product-analytics/ProductAnalyticsSDKInstructions'
import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey, type TeamPublicType, type TeamType } from '~/types'

const sessionReplayOnboardingToggle = (
    currentTeam: TeamType | TeamPublicType | null,
    selectedProducts: ProductKey[]
): ProductConfigOption => {
    const userDecision =
        currentTeam?.session_recording_opt_in ||
        selectedProducts.includes(ProductKey.SESSION_REPLAY) ||
        currentTeam?.product_intents?.some((intent) => intent.product_type === ProductKey.SESSION_REPLAY)

    return {
        title: 'Enable session recordings',
        description: `Turn on session recordings and watch how users experience your app. We will also turn on console log and network performance recording. You can change these settings any time in the settings panel.`,
        teamProperty: 'session_recording_opt_in',
        // TRICKY: if someone has shown secondary (or tertiary or...) product intent for replay we want to include it as enabled
        // particularly while we're not taking people through every product onboarding they showed interest in
        value: userDecision ?? false,
        type: 'toggle',
        visible: true,
    }
}

const ProductAnalyticsConfigStep = ({ options }: { options: ProductConfigOption[] }): JSX.Element => {
    // mount newDashboardLogic for the entire onboarding flow — same intent as the legacy view
    useValues(newDashboardLogic)
    return <OnboardingProductConfiguration options={options} />
}

export const productAnalyticsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => {
        if (ctx.role === 'secondary') {
            return [
                {
                    id: `${OnboardingStepKey.INSTALL}:${ProductKey.PRODUCT_ANALYTICS}`,
                    productKey: ProductKey.PRODUCT_ANALYTICS,
                    stepKey: OnboardingStepKey.INSTALL,
                    role: ctx.role,
                    setupTaskId: SetupTaskId.IngestFirstEvent,
                    dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
                    render: () => (
                        <OnboardingInstallStep
                            sdkInstructionMap={ProductAnalyticsSDKInstructions}
                            sdkTagOverrides={ProductAnalyticsSDKTagOverrides}
                        />
                    ),
                },
            ]
        }

        const selectedProducts = [ctx.primary, ...ctx.secondaries]
        const options: ProductConfigOption[] = [
            {
                title: 'Autocapture frontend interactions',
                description: `If you use our JavaScript, React Native or iOS libraries, we'll automagically
            capture frontend interactions like clicks, submits, and more. Fine-tune what you
            capture directly in your code snippet.`,
                teamProperty: 'autocapture_opt_out',
                value: !ctx.currentTeam?.autocapture_opt_out,
                type: 'toggle',
                inverseToggle: true,
                visible: true,
            },
            {
                title: 'Enable heatmaps',
                description: `If you use our JavaScript libraries, we can capture general clicks, mouse movements,
                   and scrolling to create heatmaps.
                   No additional events are created, and you can disable this at any time.`,
                teamProperty: 'heatmaps_opt_in',
                value: ctx.currentTeam?.heatmaps_opt_in ?? true,
                type: 'toggle',
                visible: true,
            },
            {
                title: 'Enable web vitals autocapture',
                description: `Uses Google's web vitals library to automagically capture performance information.`,
                teamProperty: 'autocapture_web_vitals_opt_in',
                value: ctx.currentTeam?.autocapture_web_vitals_opt_in ?? true,
                type: 'toggle',
                visible: true,
            },
            sessionReplayOnboardingToggle(ctx.currentTeam, selectedProducts),
            {
                title: 'Capture console logs',
                description: `Automatically enable console log capture`,
                teamProperty: 'capture_console_log_opt_in',
                value: true,
                type: 'toggle',
                visible: false,
            },
            {
                title: 'Capture network performance',
                description: `Automatically enable network performance capture`,
                teamProperty: 'capture_performance_opt_in',
                value: true,
                type: 'toggle',
                visible: false,
            },
        ]
        const filteredOptions = options.filter((option) => option.teamProperty !== 'session_recording_opt_in')

        return [
            {
                id: `${OnboardingStepKey.INSTALL}:${ProductKey.PRODUCT_ANALYTICS}`,
                productKey: ProductKey.PRODUCT_ANALYTICS,
                stepKey: OnboardingStepKey.INSTALL,
                role: ctx.role,
                setupTaskId: SetupTaskId.IngestFirstEvent,
                // Same dedupKey as the secondary branch above — without this on the
                // primary install step, picking Product Analytics + Session Replay (or
                // any other posthog-js product) would render two install steps because
                // the survivor here would carry no dedupKey for the secondary to match.
                dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
                render: () => (
                    <OnboardingInstallStep
                        sdkInstructionMap={ProductAnalyticsSDKInstructions}
                        sdkTagOverrides={ProductAnalyticsSDKTagOverrides}
                    />
                ),
            },
            {
                id: `${OnboardingStepKey.PRODUCT_CONFIGURATION}:${ProductKey.PRODUCT_ANALYTICS}`,
                productKey: ProductKey.PRODUCT_ANALYTICS,
                stepKey: OnboardingStepKey.PRODUCT_CONFIGURATION,
                role: ctx.role,
                render: () => <ProductAnalyticsConfigStep options={filteredOptions} />,
            },
            {
                id: `${OnboardingStepKey.SESSION_REPLAY}:${ProductKey.PRODUCT_ANALYTICS}`,
                productKey: ProductKey.PRODUCT_ANALYTICS,
                stepKey: OnboardingStepKey.SESSION_REPLAY,
                role: ctx.role,
                render: () => <OnboardingSessionReplayConfiguration />,
            },
        ]
    },
    completeRedirectUrl: () => urls.insightQuickStart(),
}
