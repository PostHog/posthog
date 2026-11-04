import { useActions } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MCPListeningIndicator } from '../onboarding/MCPAnalyticsInstall'
import { MCPSetupMode } from '../setupMode/MCPSetupMode'
import { mcpSetupModeLogic } from '../setupMode/mcpSetupModeLogic'

const COPY = {
    title: 'Step 1: Wrap your MCP server',
    lead: 'Install with the Wizard or your own coding agent, then call a tool. Setup guides you through each step.',
    start: 'Start setup',
}

/**
 * The setup screen's install card while setup mode is on. The install commands live in setup mode's
 * connect step, so the card only starts setup and shows whether the server has connected yet.
 */
export function MCPSetupCard({ preview }: { preview: boolean }): JSX.Element {
    const { openSetupMode } = useActions(mcpSetupModeLogic)

    return (
        <div className="mt-2 flex flex-col overflow-hidden rounded border border-primary bg-surface-primary">
            <div className="flex flex-col items-start gap-3 px-4 pb-4 pt-3.5">
                <div className="flex flex-col gap-1">
                    <span className="text-base font-semibold">{COPY.title}</span>
                    <span className="text-sm text-secondary">{COPY.lead}</span>
                </div>
                <LemonButton
                    type="primary"
                    sideIcon={<IconArrowRight />}
                    disabledReason={preview ? 'Setup starts from the live setup screen' : undefined}
                    onClick={() => openSetupMode('start_button')}
                    data-attr="mcp-analytics-start-setup"
                >
                    {COPY.start}
                </LemonButton>
            </div>
            <div className="border-t border-primary px-4 py-2.5 text-xs">
                <MCPListeningIndicator />
            </div>
            <MCPSetupMode />
        </div>
    )
}
