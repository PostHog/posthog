import { memo } from 'react'

import { IconWrench } from '@posthog/icons'

import { ToolActivity } from './ToolActivity'
import { compactInput, formatInput, getContentText, stripCodeFences } from './toolContentUtils'
import { ToolBody, ToolBodySection, ToolOutput } from './ToolOutput'
import type { ToolRendererProps } from './toolRegistry'

export interface McpToolPresentation {
    title: string
    /** Compact mono input preview for the header's second line. */
    subtitle: JSX.Element | undefined
    /** Collapsible input/output accordion body. */
    body: JSX.Element | undefined
}

/**
 * The shared MCP tool-card presentation: PostHog `exec` inner tools read `Call <tool>`; other MCP
 * tools read `Call <server> – <tool> (MCP)`; non-MCP built-ins show their friendly title. The
 * subtitle is a compact input preview and the body shows the full input plus any text output.
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
    const preview = hasInput ? compactInput(inputForPreview) : ''
    const output = stripCodeFences(getContentText(message.content))

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
                {formattedInput && <ToolOutput>{formattedInput}</ToolOutput>}
                {output && (
                    <ToolBodySection divided={!!formattedInput}>
                        <ToolOutput>{output}</ToolOutput>
                    </ToolBodySection>
                )}
            </ToolBody>
        ) : undefined

    return {
        title,
        subtitle: preview ? <span className="font-mono">{preview}</span> : undefined,
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
    const { title, subtitle, body } = getMcpToolPresentation(message, displayName)

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconWrench />}
            title={title}
            subtitle={subtitle}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})
