import { ProductKey } from '@posthog/query-frontend/schema/schema-general'

import { OnboardingInstallStep } from 'scenes/onboarding/sdks/OnboardingInstallStep'
import { SurveysSDKInstructions } from 'scenes/onboarding/sdks/surveys/SurveysSDKInstructions'
import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'scenes/onboarding/types'
import { urls } from 'scenes/urls'

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
