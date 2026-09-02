import { MetricsSDKInstructions } from 'scenes/onboarding/legacy/sdks/metrics/MetricsSDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import { type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
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
            // No dedupKey with Logs: both send over OTel, but the install steps are not
            // functionally identical. Metrics is OTLP/scrape-agent only; Logs offers 10
            // SDK-specific flows (Node.js, Python, Go, Java, mobile) plus its own OTel
            // config. Sharing a key would collapse the two and drop the loser's
            // instruction map depending on which product is primary.
            render: () => <OnboardingInstallStep sdkInstructionMap={MetricsSDKInstructions} hideInstallationCheck />,
        },
    ],
    completeRedirectUrl: () => urls.metrics(),
}
