import { router } from 'kea-router'
import posthog from 'posthog-js'

import { IconMCP } from '@posthog/icons'

import { CommandBlock } from 'lib/components/CommandBlock/CommandBlock'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { useMCPAnalyticsWizardCommand } from '../onboarding/MCPAnalyticsInstall'
import type { MCPAnalyticsNudgeSurface } from './mcpAnalyticsNudgeLogic'

export const MCP_ANALYTICS_NUDGE_TOAST_ID = 'mcp-analytics-nudge'

export function MCPAnalyticsNudgeToast({ surface }: { surface: MCPAnalyticsNudgeSurface }): JSX.Element {
    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()

    return (
        <div className="flex flex-col gap-1.5 py-1 pr-1 min-w-0 items-start">
            <div className="flex items-center gap-1.5 text-sm font-semibold">
                <IconMCP className="size-4 shrink-0 text-primary" />
                <span>Skip the maintenance. Let MCP analytics handle it</span>
            </div>
            <div className="flex flex-col items-start gap-1.5 ml-5.5 min-w-0 w-full">
                <div className="text-xs text-secondary leading-snug">
                    MCP analytics captures every tool call with its failure rate and latency, so you don't need custom
                    events.
                    {isCloudOrDev
                        ? ' Run the Wizard in your MCP server repository. The setup agent installs it for you:'
                        : null}
                </div>
                {isCloudOrDev && (
                    <CommandBlock
                        command={command}
                        copyLabel="MCP analytics wizard command"
                        ariaLabel="Copy MCP analytics wizard command"
                        size="sm"
                        decoration="rainbow"
                        silentCopy
                        condensed
                        onCopy={() => posthog.capture('mcp analytics nudge command copied', { surface })}
                        className="bg-surface-secondary border border-primary !m-0 hover:border-accent max-w-full"
                    />
                )}
                <LemonButton
                    type="primary"
                    size="small"
                    className="!mx-0"
                    data-attr="mcp-analytics-nudge-toast-cta"
                    onClick={() => {
                        posthog.capture('mcp analytics nudge cta clicked', { surface })
                        lemonToast.dismiss(MCP_ANALYTICS_NUDGE_TOAST_ID)
                        router.actions.push(urls.mcpAnalytics())
                    }}
                >
                    Set up MCP analytics
                </LemonButton>
            </div>
        </div>
    )
}
