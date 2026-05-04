import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'products/growth/frontend/onboarding/flow/types'
import { ExperimentsSDKInstructions } from 'products/growth/frontend/onboarding/sdks/experiments/ExperimentsSDKInstructions'
import { OnboardingInstallStep } from 'products/growth/frontend/onboarding/sdks/OnboardingInstallStep'

// `completeRedirectUrl` intentionally omitted: experiments falls through to
// urls.default() (no curated post-onboarding landing page yet).
export const experimentsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.EXPERIMENTS}`,
            productKey: ProductKey.EXPERIMENTS,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
            render: () => <OnboardingInstallStep sdkInstructionMap={ExperimentsSDKInstructions} />,
        },
    ],
}
