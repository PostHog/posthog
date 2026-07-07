import { FeatureFlagsSDKInstructions } from 'scenes/onboarding/legacy/sdks/feature-flags/FeatureFlagsSDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const featureFlagsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.FEATURE_FLAGS}`,
            productKey: ProductKey.FEATURE_FLAGS,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
            render: () => <OnboardingInstallStep sdkInstructionMap={FeatureFlagsSDKInstructions} />,
        },
    ],
    completeRedirectUrl: () => urls.featureFlags(),
}
