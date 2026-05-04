import { ExperimentsSDKInstructions } from 'scenes/onboarding/sdks/experiments/ExperimentsSDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/sdks/OnboardingInstallStep'
import { INSTALL_DEDUP_KEYS, type StepProvider } from 'scenes/onboarding/types'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const experimentsOnboardingSteps: StepProvider = (ctx) => [
    {
        id: `${OnboardingStepKey.INSTALL}:${ProductKey.EXPERIMENTS}`,
        productKey: ProductKey.EXPERIMENTS,
        stepKey: OnboardingStepKey.INSTALL,
        role: ctx.role,
        dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
        render: () => <OnboardingInstallStep sdkInstructionMap={ExperimentsSDKInstructions} />,
    },
]
