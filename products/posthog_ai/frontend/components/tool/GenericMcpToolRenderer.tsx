import { memo } from 'react'

import { IconWrench } from '@posthog/icons'

import { ToolActivity } from './ToolActivity'
import { compactInput, formatInput, getContentText, stripCodeFences } from './toolContentUtils'
import { ToolBody, ToolBodySection, ToolOutput } from './ToolOutput'
import type { ToolRendererProps } from './toolRegistry'

/**
 * The catch-all tool card — user-installed MCP tools, unmapped PostHog `exec` inner tools, and Claude
 * built-ins without a bespoke renderer. PostHog `exec` inner tools read `Call <tool>`; other MCP tools
 * read `Call <server> – <tool> (MCP)`; non-MCP built-ins show their friendly title. A compact input
 * preview sits on the second line and the body shows any text output. Replaces the old
 * `FallbackMcpToolRenderer`.
 */
export const GenericMcpToolRenderer = memo(function GenericMcpToolRenderer(props: ToolRendererProps): JSX.Element {
    const { message, icon, displayName, turnComplete, turnCancelled } = props

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

    // Subagent / MCP / unmapped tools show both the full input and the text output in the body.
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

    return (
        <ToolActivity
            message={message}
            icon={icon ?? <IconWrench />}
            title={title}
            subtitle={preview ? <span className="font-mono">{preview}</span> : undefined}
            body={body}
            turnComplete={turnComplete}
            turnCancelled={turnCancelled}
        />
    )
})
