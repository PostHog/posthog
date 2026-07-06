import { useValues } from 'kea'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { cn } from 'lib/utils/css-classes'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'
import { WIZARD_HOG_URL } from 'scenes/onboarding/shared/wizardHog'
import { teamLogic } from 'scenes/teamLogic'

import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'

export const MCP_ANALYTICS_DOCS_URL = 'https://posthog.com/docs/mcp-analytics'

// The shared wizard hook only emits the base command; slot in our subcommand right
// after the package reference (before any flags like `--region eu`). Matching
// `@posthog/wizard@<anything>` keeps this working if the hook ever pins a version;
// the fallback guarantees the subcommand is never silently dropped.
const WIZARD_PKG_RE = /@posthog\/wizard@\S+/

export function useMCPAnalyticsWizardCommand(): { command: string; isCloudOrDev: boolean } {
    const { wizardCommand, isCloudOrDev } = useWizardCommand()
    const { currentTeam } = useValues(teamLogic)
    const base = WIZARD_PKG_RE.test(wizardCommand)
        ? wizardCommand.replace(WIZARD_PKG_RE, '$& mcp-analytics')
        : `${wizardCommand} mcp-analytics`
    // Pin the project so the wizard targets this team directly — and, once the consent
    // screen honors the hint, pre-selects it. Harmless if the user authorizes the same project.
    const command = currentTeam?.id ? `${base} --project-id=${currentTeam.id}` : base
    return { command, isCloudOrDev }
}

/** Live "are events arriving yet?" status, driven by the same poll the scene uses. */
export function MCPListeningIndicator(): JSX.Element {
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

/**
 * The "instrument in one command" hero — heading, rainbow wizard command, project nudge, and
 * a live listening indicator. Shared by the onboarding step and the in-scene empty state so the
 * two surfaces can't drift.
 */
export function MCPAnalyticsInstallHero(): JSX.Element {
    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()
    const { currentTeam } = useValues(teamLogic)

    return (
        <div className="w-full max-w-2xl mx-auto space-y-8">
            <div className="text-center space-y-3">
                <h2 className="text-2xl font-bold">Skip the setup. Instrument in one command.</h2>
                <p className="text-muted">
                    Run this from your MCP server's project root. The wizard detects how your server is built, installs
                    the <code>@posthog/mcp</code> SDK, wires up your credentials, and starts capturing every tool call,
                    agent intent, and failure.
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
                                    Authorize access to <strong>{currentTeam.name}</strong> when prompted.{' '}
                                </>
                            ) : null}
                            Then make a tool call — this page fills in the moment events arrive.
                        </p>
                    </div>
                </div>
            )}

            <div className="flex flex-col items-center gap-2">
                <MCPListeningIndicator />
                <LemonButton type="tertiary" size="small" to={MCP_ANALYTICS_DOCS_URL} targetBlank>
                    Prefer to set it up manually? Read the docs
                </LemonButton>
            </div>
        </div>
    )
}
