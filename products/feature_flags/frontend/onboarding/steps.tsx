import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'products/growth/frontend/onboarding/flow/types'
import { FeatureFlagsSDKInstructions } from 'products/growth/frontend/onboarding/sdks/feature-flags/FeatureFlagsSDKInstructions'
import { OnboardingInstallStep } from 'products/growth/frontend/onboarding/sdks/OnboardingInstallStep'

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
