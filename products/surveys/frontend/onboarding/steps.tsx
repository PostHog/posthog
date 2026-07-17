import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import { SurveysSDKInstructions } from 'scenes/onboarding/legacy/sdks/surveys/SurveysSDKInstructions'
import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const surveysOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.SURVEYS}`,
            productKey: ProductKey.SURVEYS,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
            render: () => <OnboardingInstallStep sdkInstructionMap={SurveysSDKInstructions} />,
        },
    ],
    completeRedirectUrl: () => urls.surveyWizard(),
}
