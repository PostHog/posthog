import { useActions, useValues } from 'kea'

import { IconCopy } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { MCPListeningIndicator } from '../onboarding/MCPAnalyticsInstall'
import { MCPSetupMode } from '../setupMode/MCPSetupMode'
import { mcpAnalyticsSetupLogic } from './mcpAnalyticsSetupLogic'
import { MCPAnalyticsSetupProgress } from './MCPAnalyticsSetupProgress'
import { MCPSetupDemoCard } from './MCPSetupDemoCard'

/**
 * The setup screen's actions while setup mode is on: the agent prompt as the second install route,
 * next to the wizard command the shared empty state renders. Copying either one opens setup mode.
 */
export function MCPSetupDoorActions({ mode, preview }: { mode: ProductEmptyStateMode; preview: boolean }): JSX.Element {
    const { agentPrompt } = useValues(mcpAnalyticsSetupLogic)
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))
    const { isCloudOrDev } = useValues(preflightLogic)

    return (
        <>
            {agentPrompt ? (
                <div className="flex flex-col gap-2">
                    <div className="text-xs text-tertiary">
                        Or ask your coding agent. Paste this prompt into Claude Code, Cursor or Codex in your server's
                        repository:
                    </div>
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
            {isCloudOrDev && !preview ? <MCPAnalyticsSetupProgress mode={mode} /> : null}
            <div className="text-xs">
                <MCPListeningIndicator />
            </div>
            <MCPSetupDemoCard mode={mode} preview={preview} />
            <MCPSetupMode />
        </>
    )
}
