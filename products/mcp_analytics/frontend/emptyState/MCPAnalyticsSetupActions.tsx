import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet/CodeSnippet'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { mcpAnalyticsSetupLogic } from './mcpAnalyticsSetupLogic'
import { MCPAnalyticsSetupProgress } from './MCPAnalyticsSetupProgress'

export function MCPAnalyticsSetupActions({
    mode,
    preview,
}: {
    mode: ProductEmptyStateMode
    preview: boolean
}): JSX.Element {
    const { agentPromptOpen, agentPrompt } = useValues(mcpAnalyticsSetupLogic)
    const { setAgentPromptOpen } = useActions(mcpAnalyticsSetupLogic)
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))
    const { isCloudOrDev } = useValues(preflightLogic)

    return (
        <>
            <LemonButton
                type="secondary"
                icon={<IconSparkles />}
                className="self-start"
                data-attr="mcp-analytics-install-with-agent"
                disabledReason={agentPrompt ? undefined : 'Select a project to get installation instructions.'}
                onClick={() => {
                    setAgentPromptOpen(true)
                    reportSetupInteraction('agent instructions opened', mode, null, preview)
                }}
            >
                Install with your agent
            </LemonButton>
            <LemonModal
                title="Install with your coding agent"
                isOpen={agentPromptOpen}
                onClose={() => setAgentPromptOpen(false)}
                width={640}
            >
                <p>Open the repository containing your MCP server in your coding agent, then paste this prompt.</p>
                <CodeSnippet
                    wrap
                    compact
                    maxLinesWithoutExpansion={5}
                    thing="installation prompt"
                    onCopy={() => reportSetupInteraction('agent prompt copied', mode, 'agent', preview)}
                >
                    {agentPrompt}
                </CodeSnippet>
                <p className="text-secondary mt-4 mb-0">
                    After setup, call an existing tool from your server. This page updates when its tool-call event
                    arrives.
                </p>
            </LemonModal>
            {isCloudOrDev && !preview ? <MCPAnalyticsSetupProgress mode={mode} /> : null}
        </>
    )
}
