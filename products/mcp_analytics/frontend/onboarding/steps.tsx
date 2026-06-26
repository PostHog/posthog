import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { cn } from 'lib/utils/css-classes'
import { onboardingLogic } from 'scenes/onboarding/legacy/onboardingLogic'
import { OnboardingStep } from 'scenes/onboarding/legacy/OnboardingStep'
import { WIZARD_HOG_URL } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep/WizardCommandBlock'
import { type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'

const DOCS_URL = 'https://posthog.com/docs/mcp-analytics'

/** Live "are events arriving yet?" status, driven by the same poll the scene uses. */
function ListeningIndicator(): JSX.Element {
    const { onboardingState } = useValues(mcpAnalyticsOnboardingLogic)

    if (onboardingState === 'onboarded') {
        return (
            <div className="flex items-center gap-2 text-success">
                <IconCheckCircle className="text-lg" />
                <span>Tool calls are flowing — you're all set.</span>
            </div>
        )
    }
    if (onboardingState === 'connected-no-calls') {
        return (
            <div className="flex items-center gap-2 text-secondary">
                <IconCheckCircle className="text-lg text-success" />
                <span>Server connected — waiting for the first tool call…</span>
            </div>
        )
    }
    return (
        <div className="flex items-center gap-2 text-secondary">
            <Spinner />
            <span>Listening for your first MCP event…</span>
        </div>
    )
}

function MCPAnalyticsInstallStep(): JSX.Element {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const { currentTeam } = useValues(teamLogic)
    const { onboardingState } = useValues(mcpAnalyticsOnboardingLogic)
    const { completeOnboarding } = useActions(onboardingLogic)
    // The shared wizard hook only emits the base command; slot in our subcommand right
    // after the package reference (before any flags like `--region eu`). Matching
    // `@posthog/wizard@<anything>` keeps this working if the hook ever pins a version;
    // the fallback guarantees the subcommand is never silently dropped.
    const WIZARD_PKG_RE = /@posthog\/wizard@\S+/
    const command = WIZARD_PKG_RE.test(wizardCommand)
        ? wizardCommand.replace(WIZARD_PKG_RE, '$& mcp-analytics')
        : `${wizardCommand} mcp-analytics`

    // The moment tool calls start flowing the setup worked — whisk them to their data
    // instead of making them click "Go to dashboard".
    useEffect(() => {
        if (onboardingState === 'onboarded') {
            completeOnboarding()
        }
    }, [onboardingState, completeOnboarding])

    return (
        <OnboardingStep title="Install" stepKey={OnboardingStepKey.INSTALL} continueText="Go to dashboard">
            <div className="mt-6 space-y-8">
                <div className="text-center max-w-2xl mx-auto space-y-3">
                    <h2 className="text-2xl font-bold">Skip the setup. Instrument in one command.</h2>
                    <p className="text-muted">
                        Run this from your MCP server's project root. The wizard detects how your server is built,
                        installs the <code>@posthog/mcp</code> SDK, wires up your credentials, and starts capturing
                        every tool call, agent intent, and failure.
                    </p>
                    <p className="text-muted text-xs">LLM inference is on us, no API key needed.</p>
                </div>

                {isCloudOrDev && (
                    <div className="flex items-center gap-6">
                        <img
                            src={WIZARD_HOG_URL}
                            alt="PostHog wizard hedgehog"
                            className={cn('w-28 h-28 hidden md:block shrink-0')}
                        />
                        <div className="flex-1 min-w-0 flex flex-col gap-3">
                            <CommandBlock
                                command={command}
                                copyLabel="MCP wizard command"
                                ariaLabel="Copy MCP analytics wizard command"
                                size="md"
                                decoration="rainbow"
                                className="bg-bg-light border border-border hover:border-primary"
                            />
                            <p className="text-xs text-muted mb-0">
                                {currentTeam?.name ? (
                                    <>
                                        When the wizard asks which project to use, choose{' '}
                                        <strong>{currentTeam.name}</strong>.{' '}
                                    </>
                                ) : null}
                                Then make a tool call — this page fills in the moment events arrive.
                            </p>
                        </div>
                    </div>
                )}

                <div className="flex flex-col items-center gap-2">
                    <ListeningIndicator />
                    <LemonButton type="tertiary" size="small" to={DOCS_URL}>
                        Prefer to set it up manually? Read the docs
                    </LemonButton>
                </div>
            </div>
        </OnboardingStep>
    )
}

export const mcpAnalyticsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.MCP_ANALYTICS}`,
            productKey: ProductKey.MCP_ANALYTICS,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            render: () => <MCPAnalyticsInstallStep />,
        },
    ],
    completeRedirectUrl: () => urls.mcpAnalyticsDashboard(),
}
