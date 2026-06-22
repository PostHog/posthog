import { LemonBanner, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import {
    WorkflowsSDKInstructions,
    WorkflowsSDKTagOverrides,
} from 'scenes/onboarding/legacy/sdks/workflows/WorkflowsSDKInstructions'
import { type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

const WorkflowsInstallHeader = (): JSX.Element => {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()

    return (
        <div className="mt-2 space-y-4">
            <p className="text-sm">
                Workflows is a no-code product — installing an SDK is optional. However, with an SDK installed, any
                captured or custom event can be used as a{' '}
                <Link
                    to="https://posthog.com/docs/workflows/workflow-builder#triggers"
                    target="_blank"
                    targetBlankIcon={false}
                >
                    workflow trigger
                </Link>
                . Without an SDK, you're limited to webhook and manual triggers.
            </p>
            {isCloudOrDev && (
                <>
                    <LemonBanner type="info" hideIcon>
                        <h3 className="pb-1">AI setup wizard</h3>
                        <div className="flex flex-col p-2">
                            <p className="font-normal pb-1">
                                The fastest way to get started. Run this command from your project root — it
                                automatically detects your framework, installs PostHog, and sets up event capture.
                            </p>
                            <CodeSnippet language={Language.Bash}>{wizardCommand}</CodeSnippet>
                        </div>
                    </LemonBanner>
                    <p className="text-sm">
                        After the wizard finishes, <Link to="/workflows/channels">configure a channel</Link> then head
                        to the <Link to="/workflows">workflow builder</Link> to create your first automation.
                    </p>
                    <div className="flex items-center gap-3">
                        <div className="flex-1 border-t border-border" />
                        <span className="text-muted font-semibold text-xs uppercase">Or, set up manually</span>
                        <div className="flex-1 border-t border-border" />
                    </div>
                </>
            )}
        </div>
    )
}

export const workflowsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.WORKFLOWS}`,
            productKey: ProductKey.WORKFLOWS,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            render: () => (
                <OnboardingInstallStep
                    sdkInstructionMap={WorkflowsSDKInstructions}
                    sdkTagOverrides={WorkflowsSDKTagOverrides}
                    header={<WorkflowsInstallHeader />}
                />
            ),
        },
    ],
    completeRedirectUrl: () => urls.workflows(),
}
