import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { WavingHog } from 'lib/components/hedgehogs'

import type { MCPOnboardingState } from './mcpAnalyticsOnboardingLogic'
import {
    MCP_ANALYTICS_DOCS_URL,
    MCPAnalyticsInstallHero,
    MCPListeningIndicator,
    useMCPAnalyticsWizardCommand,
} from './onboarding/MCPAnalyticsInstall'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

/** Branded loading state shown while we work out whether the project has MCP events yet. */
export function MCPAnalyticsLoading(): JSX.Element {
    return (
        <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
            <HedgehogMagnifyingGlass className="w-32 h-32" />
            <div className="flex items-center gap-2 text-secondary">
                <Spinner />
                <span>Checking for MCP activity…</span>
            </div>
        </div>
    )
}

/**
 * Shown once the server is wired up (`$mcp_initialize` seen) but no tool call has landed yet.
 * They're already instrumented, so the hero is "make a tool call" + the live indicator; the
 * wizard command is demoted to a secondary "instrument another server" affordance.
 */
function ConnectedNoCalls(): JSX.Element {
    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()

    return (
        <div className="flex flex-col items-center text-center gap-6 py-12 max-w-xl mx-auto">
            <WavingHog className="w-32 h-32" />
            <div className="space-y-2">
                <h2 className="text-2xl font-bold">You're connected — now make a tool call</h2>
                <p className="text-muted m-0">
                    We've seen your MCP server connect, but it hasn't handled a tool call yet. Trigger a tool from your
                    agent and this page fills in on its own.
                </p>
            </div>
            <MCPListeningIndicator />
            {isCloudOrDev && (
                <div className="w-full flex flex-col items-center gap-2 pt-2">
                    <p className="text-xs text-muted m-0">Instrumenting another server? Re-run setup:</p>
                    <CommandBlock
                        command={command}
                        copyLabel="MCP wizard command"
                        ariaLabel="Copy MCP analytics wizard command"
                        size="sm"
                        className="bg-bg-light border border-border"
                    />
                </div>
            )}
            <LemonButton type="tertiary" size="small" to={MCP_ANALYTICS_DOCS_URL} targetBlank>
                Read the docs
            </LemonButton>
        </div>
    )
}

/** Shown until the project captures its first `$mcp_tool_call`. Tailors by signal state. */
export function MCPAnalyticsOnboarding({ state }: { state: Exclude<MCPOnboardingState, 'onboarded'> }): JSX.Element {
    if (state === 'connected-no-calls') {
        return <ConnectedNoCalls />
    }
    // not-instrumented: lead with the full install hero — same treatment as the onboarding page.
    return (
        <div className="py-8">
            <MCPAnalyticsInstallHero />
        </div>
    )
}
