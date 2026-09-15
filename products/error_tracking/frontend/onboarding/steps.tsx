import { SetupTaskId } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { OnboardingErrorTrackingAlertsStep } from 'scenes/onboarding/legacy/error-tracking/OnboardingErrorTrackingAlertsStep'
import { OnboardingErrorTrackingSourceMapsStep } from 'scenes/onboarding/legacy/error-tracking/OnboardingErrorTrackingSourceMapsStep'
import {
    ErrorTrackingSDKDocsLinkOverrides,
    ErrorTrackingSDKInstructions,
} from 'scenes/onboarding/legacy/sdks/error-tracking/ErrorTrackingSDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import type { WizardOverrides } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep/types'
import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const errorTrackingOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => {
        // The `error-tracking` wizard subcommand is still rolling out, so the install step keeps the
        // base SDK install command until its flag is on.
        const wizardOverrides: WizardOverrides | undefined = ctx.featureFlags[FEATURE_FLAGS.ERROR_TRACKING_NEW_WIZARD]
            ? {
                  subcommand: 'error-tracking',
                  intro: 'The setup agent detects your framework, installs the SDK if needed, and adds exception capture and source map upload.',
                  description:
                      "Detects your framework, installs the SDK if needed, and adds exception capture and source map upload so errors arrive with readable stack traces. Commit the changes and open a PR when you're ready.",
              }
            : undefined
        const installStep = {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.ERROR_TRACKING}`,
            productKey: ProductKey.ERROR_TRACKING,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            setupTaskId: SetupTaskId.EnableErrorTracking,
            // Same posthog-js install as Product Analytics / Web Analytics / etc. When
            // those products are also picked, only one install step is shown — but the
            // `EnableErrorTracking` task still gets ticked because the dedup pass merges
            // setupTaskIds from dropped descriptors into the survivor.
            dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
            render: () => (
                <OnboardingInstallStep
                    sdkInstructionMap={ErrorTrackingSDKInstructions}
                    sdkDocsLinkOverrides={ErrorTrackingSDKDocsLinkOverrides}
                    wizardOverrides={wizardOverrides}
                />
            ),
        }
        if (ctx.role === 'secondary') {
            return [installStep]
        }
        return [
            installStep,
            {
                id: `${OnboardingStepKey.SOURCE_MAPS}:${ProductKey.ERROR_TRACKING}`,
                productKey: ProductKey.ERROR_TRACKING,
                stepKey: OnboardingStepKey.SOURCE_MAPS,
                role: ctx.role,
                setupTaskId: SetupTaskId.UploadSourceMaps,
                render: () => <OnboardingErrorTrackingSourceMapsStep />,
            },
            {
                id: `${OnboardingStepKey.ALERTS}:${ProductKey.ERROR_TRACKING}`,
                productKey: ProductKey.ERROR_TRACKING,
                stepKey: OnboardingStepKey.ALERTS,
                role: ctx.role,
                render: () => <OnboardingErrorTrackingAlertsStep />,
            },
        ]
    },
    completeRedirectUrl: () => urls.errorTracking(),
}
