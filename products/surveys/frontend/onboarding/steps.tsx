import { OnboardingInstallStep } from 'scenes/onboarding/sdks/OnboardingInstallStep'
import { SurveysSDKInstructions } from 'scenes/onboarding/sdks/surveys/SurveysSDKInstructions'
import { INSTALL_DEDUP_KEYS, type StepProvider } from 'scenes/onboarding/types'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const surveysOnboardingSteps: StepProvider = (ctx) => [
    {
        id: `${OnboardingStepKey.INSTALL}:${ProductKey.SURVEYS}`,
        productKey: ProductKey.SURVEYS,
        stepKey: OnboardingStepKey.INSTALL,
        role: ctx.role,
        dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
        render: () => <OnboardingInstallStep sdkInstructionMap={SurveysSDKInstructions} />,
    },
]
