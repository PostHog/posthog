import './MCPHowItWorksWrapStage.scss'

import { useActions } from 'kea'
import { useState } from 'react'

import { IconCheck, IconCopy, IconLogomark, IconMCP, IconWrench } from '@posthog/icons'

import { condenseCommand } from 'lib/components/CommandBlock/CommandBlock'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductEmptyStateMode } from 'lib/components/ProductEmptyState/types'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'

import { ProductKey } from '~/queries/schema/schema-general'

import { useMCPAnalyticsWizardCommand } from '../onboarding/MCPAnalyticsInstall'

const COPIED_MS = 1600

export function MCPHowItWorksWrapStage({
    mode,
    preview,
}: {
    mode: ProductEmptyStateMode
    preview: boolean
}): JSX.Element {
    const [copied, setCopied] = useState(false)
    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()
    const { reportSetupInteraction } = useActions(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))

    const copyCommand = (): void => {
        void copyToClipboard(command, 'MCP analytics wizard command').then((ok) => {
            if (ok) {
                reportSetupInteraction('wizard command copied', mode, 'wizard', preview)
                setCopied(true)
                window.setTimeout(() => setCopied(false), COPIED_MS)
            }
        })
    }

    return (
        <>
            <div className="MCPHowItWorks__ring">
                <span className="MCPHowItWorks__ph-badge MCPHowItWorks__rv [--d:0.7s]">
                    <IconLogomark />
                </span>
                <div className="MCPHowItWorks__server MCPHowItWorks__rv [--d:0.2s]">
                    <div className="MCPHowItWorks__server-top">
                        <IconMCP />
                        MCP server
                    </div>
                    {[0, 1, 2].map((tool) => (
                        <div key={tool} className="MCPHowItWorks__tool">
                            <IconWrench />
                            <i />
                        </div>
                    ))}
                    <span className="MCPHowItWorks__live MCPHowItWorks__rv [--d:1.5s]">
                        <IconCheck />
                    </span>
                </div>
            </div>
            <div className="MCPHowItWorks__wiz MCPHowItWorks__rv [--d:1s]">
                <span className="MCPHowItWorks__wiz-prompt">$</span>
                <span className="MCPHowItWorks__wiz-cmd">{condenseCommand(command)}</span>
                {isCloudOrDev ? (
                    <button
                        type="button"
                        className={cn('MCPHowItWorks__copy', copied && 'MCPHowItWorks__copy--done')}
                        aria-label="Copy command"
                        onClick={copyCommand}
                        data-attr="mcp-analytics-how-it-works-copy-wizard"
                    >
                        {copied ? <IconCheck /> : <IconCopy />}
                    </button>
                ) : null}
            </div>
        </>
    )
}
