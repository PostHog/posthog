import { MetricsSDKInstructions } from 'scenes/onboarding/legacy/sdks/metrics/MetricsSDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const metricsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.METRICS}`,
            productKey: ProductKey.METRICS,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            // Same OTel install as Logs, so picking both products asks once.
            dedupKey: INSTALL_DEDUP_KEYS.OPENTELEMETRY,
            render: () => <OnboardingInstallStep sdkInstructionMap={MetricsSDKInstructions} hideInstallationCheck />,
        },
    ],
    completeRedirectUrl: () => urls.metrics(),
}
