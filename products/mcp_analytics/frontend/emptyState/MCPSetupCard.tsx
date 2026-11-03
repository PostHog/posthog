import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ProductKey } from '~/queries/schema/schema-general'

import { MCPListeningIndicator } from '../onboarding/MCPAnalyticsInstall'
import { MCPSetupMode } from '../setupMode/MCPSetupMode'
import { mcpAnalyticsSetupLogic } from './mcpAnalyticsSetupLogic'
import { MCPAnalyticsSetupProgress } from './MCPAnalyticsSetupProgress'

const COPY = {
    title: 'Step 1: Wrap your MCP server',
    wizard: 'Run the Wizard',
    agent: 'Or ask your agent',
}

/**
 * The setup screen's install card while setup mode is on: the wizard command the shared empty state
 * renders as `children`, the agent prompt as the second route, and the listening status. Copying either
 * one opens setup mode.
 */
export function MCPSetupCard({
    mode,
    preview,
    children,
}: {
    mode: ProductEmptyStateMode
    preview: boolean
    children: ReactNode
}): JSX.Element {
    const { agentPrompt } = useValues(mcpAnalyticsSetupLogic)
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))
    const { isCloudOrDev } = useValues(preflightLogic)

    return (
        <div className="mt-2 flex flex-col overflow-hidden rounded border border-primary bg-surface-primary">
            <span className="px-4 pb-1 pt-3.5 text-base font-semibold">{COPY.title}</span>
            {children ? (
                <div className="flex flex-col gap-2 px-4 py-2.5">
                    <span className="text-xs font-semibold text-secondary">{COPY.wizard}</span>
                    {children}
                </div>
            ) : null}
            {agentPrompt ? (
                <div className="flex flex-col gap-2 px-4 pb-4 pt-2.5">
                    <span className="text-xs font-semibold text-secondary">{COPY.agent}</span>
                    <div className="flex min-w-0 items-center gap-2 rounded border border-primary bg-surface-primary py-1 pl-3 pr-1">
                        <span className="min-w-0 flex-1 truncate font-mono text-xs text-secondary">{agentPrompt}</span>
                        <LemonButton
                            size="small"
                            type="secondary"
                            icon={<IconCopy />}
                            onClick={() =>
                                void copyToClipboard(agentPrompt, 'installation prompt').then((copied) => {
                                    if (copied) {
                                        reportSetupInteraction('agent prompt copied', mode, 'agent', preview)
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
            {isCloudOrDev && !preview ? (
                <div className="px-4 pb-2.5 empty:hidden">
                    <MCPAnalyticsSetupProgress mode={mode} />
                </div>
            ) : null}
            <div className="border-t border-primary px-4 py-2.5 text-xs">
                <MCPListeningIndicator />
            </div>
            <MCPSetupMode />
        </div>
    )
}
