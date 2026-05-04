import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'products/growth/frontend/onboarding/flow/types'
import { OnboardingInstallStep } from 'products/growth/frontend/onboarding/sdks/OnboardingInstallStep'
import { SurveysSDKInstructions } from 'products/growth/frontend/onboarding/sdks/surveys/SurveysSDKInstructions'

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
