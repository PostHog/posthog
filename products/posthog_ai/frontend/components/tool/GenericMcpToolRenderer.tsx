import { memo } from 'react'

import { IconWrench } from '@posthog/icons'

import { ToolActivity } from './ToolActivity'
import { formatInput, getContentText, stripCodeFences } from './toolContentUtils'
import { ToolBody, ToolBodySection, ToolOutput } from './ToolOutput'
import type { ToolRendererProps } from './toolRegistry'

export interface McpToolPresentation {
    title: string
    /** Collapsible input/output accordion body. */
    body: JSX.Element | undefined
}

/**
 * The shared MCP tool-card presentation: PostHog `exec` inner tools read `Call <tool>`; other MCP
 * tools read `Call <server> – <tool> (MCP)`; non-MCP built-ins show their friendly title. The
 * body shows the input and text output on demand.
 * Used by the generic card and by `DataToolRow`, so data-tool widgets keep the same header/accordion.
 */
export function getMcpToolPresentation(
    message: ToolRendererProps['message'],
    displayName?: string
): McpToolPresentation {
    const isPostHogExec = !!message.innerToolName
    const isMcp =
        isPostHogExec || (!!message.rawServerName && !!message.rawToolName && message.rawServerName !== 'claude')
    const serverName = isPostHogExec ? 'posthog' : message.rawServerName
    const toolLabel =
        message.innerToolName || message.rawToolName || message.claudeToolName || displayName || message.resolvedKey
    const inputForPreview = message.innerInput ?? message.rawInput
    const hasInput = !!inputForPreview && Object.keys(inputForPreview).length > 0
    const output =
        stripCodeFences(getContentText(message.content)) ||
        (message.rawOutput !== undefined ? formatInput(message.rawOutput) : '')

    // Plain neutral title text, matching the built-in tool cards (e.g. "Read N lines"). A single text
    // node is also one flex item, so the header's `inline-flex` wrapper keeps the spaces intact.
    const title = isPostHogExec
        ? `Call ${toolLabel}`
        : isMcp
          ? `Call ${serverName} – ${toolLabel} (MCP)`
          : message.title || displayName || toolLabel

    const formattedInput = hasInput ? formatInput(inputForPreview) : ''
    const body =
        formattedInput || output ? (
            <ToolBody>
                {formattedInput && (
                    <ToolBodySection>
                        <div className="text-muted mb-1">Input</div>
                        <ToolOutput>{formattedInput}</ToolOutput>
                    </ToolBodySection>
                )}
                {output && (
                    <ToolBodySection divided={!!formattedInput}>
                        <div className="text-muted mb-1">Output</div>
                        <ToolOutput>{output}</ToolOutput>
                    </ToolBodySection>
                )}
            </ToolBody>
        ) : undefined

    return {
        title,
        body,
    }
}

/**
 * The catch-all tool card — user-installed MCP tools, unmapped PostHog `exec` inner tools, and Claude
 * built-ins without a bespoke renderer. Renders the shared MCP presentation with no always-visible
 * content. Replaces the old `FallbackMcpToolRenderer`.
 */
export const GenericMcpToolRenderer = memo(function GenericMcpToolRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props
    const { title, body } = getMcpToolPresentation(message, displayName)

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconWrench />}
            title={title}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})
