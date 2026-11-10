import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TerminalCard } from 'lib/components/CommandBlock/TerminalCard'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ProductKey } from '~/queries/schema/schema-general'

import { mcpAnalyticsSetupLogic } from '../emptyState/mcpAnalyticsSetupLogic'
import { useMCPAnalyticsWizardCommand } from '../onboarding/MCPAnalyticsInstall'

const COPY = {
    wizard: "Run the Wizard in your server's repository",
    agent: 'Or ask your coding agent',
    agentOnly: 'Ask your coding agent',
    restart: 'Restart your server when setup is done.',
}

/**
 * The two ways to install, with the Wizard's live progress under them, so an install that fails or
 * hits a limit shows its error here rather than behind setup mode.
 */
export function SetupInstallOptions(): JSX.Element {
    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()
    const { agentPrompt } = useValues(mcpAnalyticsSetupLogic)
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))

    return (
        <div className="flex flex-col gap-4 rounded border border-primary bg-surface-primary p-4">
            {/* The Wizard only works against PostHog Cloud. */}
            {isCloudOrDev ? (
                <div className="flex flex-col gap-2">
                    <span className="text-xs font-semibold text-secondary">{COPY.wizard}</span>
                    <TerminalCard
                        command={command}
                        copyLabel="MCP analytics wizard command"
                        onCopy={() => reportSetupInteraction('wizard command copied', 'needs-setup', 'wizard')}
                    />
                </div>
            ) : null}
            {agentPrompt ? (
                <div className="flex flex-col gap-2">
                    <span className="text-xs font-semibold text-secondary">
                        {isCloudOrDev ? COPY.agent : COPY.agentOnly}
                    </span>
                    <div className="flex min-w-0 items-center gap-2 rounded border border-primary py-1 pl-3 pr-1">
                        <span className="min-w-0 flex-1 truncate font-mono text-xs text-secondary" title={agentPrompt}>
                            {agentPrompt}
                        </span>
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCopy />}
                            onClick={() =>
                                void copyToClipboard(agentPrompt, 'installation prompt').then((copied) => {
                                    if (copied) {
                                        reportSetupInteraction('agent prompt copied', 'needs-setup', 'agent')
                                    }
                                })
                            }
                            data-attr="mcp-analytics-copy-agent-prompt"
                        >
                            Copy prompt
                        </LemonButton>
                    </div>
                </div>
            ) : null}
            <span className="text-sm text-secondary">{COPY.restart}</span>
        </div>
    )
}
