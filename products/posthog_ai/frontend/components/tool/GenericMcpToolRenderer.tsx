import { memo, type ReactNode } from 'react'

import { IconWrench } from '@posthog/icons'

import { ToolActivity } from './ToolActivity'
import { formatInput, getContentText, stripCodeFences } from './toolContentUtils'
import { ToolBody, ToolBodySection, ToolOutput } from './ToolOutput'
import type { ToolRendererProps } from './toolRegistry'

// ACP tool-call kinds, used as the row label when a harness sends no title and no tool name.
const KIND_LABELS: Record<string, string> = {
    read: 'Read',
    edit: 'Edit',
    delete: 'Delete',
    move: 'Move',
    search: 'Search',
    execute: 'Run command',
    think: 'Think',
    fetch: 'Web search',
}

export interface McpToolPresentation {
    title: ReactNode
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

    const titleText = isPostHogExec
        ? `Call ${toolLabel}`
        : isMcp
          ? `Call ${serverName} – ${toolLabel} (MCP)`
          : message.title || displayName || toolLabel || (message.kind && KIND_LABELS[message.kind]) || ''
    // The PostHog MCP asks the agent for a one-sentence `context` on every call. It is the only
    // harness-independent description of intent, so it reads better in the row than the command.
    const context = typeof message.rawInput.context === 'string' ? message.rawInput.context.trim() : ''
    const title = (
        <>
            <span className={message.kind === 'execute' ? 'font-mono text-xs' : undefined}>{titleText}</span>
            {context && <span className="text-muted font-normal"> · {context}</span>}
        </>
    )

    const formattedInput = hasInput ? formatInput(inputForPreview) : ''
    // Some harnesses put a shell command only in `title`, which the row truncates.
    const command = !hasInput && !isMcp && message.kind === 'execute' ? message.title || '' : ''
    const outputText = output || (message.status === 'failed' ? 'No output captured' : '')
    const body =
        formattedInput || command || outputText ? (
            <ToolBody>
                {formattedInput && (
                    <ToolBodySection>
                        <div className="text-muted mb-1">Input</div>
                        <ToolOutput>{formattedInput}</ToolOutput>
                    </ToolBodySection>
                )}
                {command && (
                    <ToolBodySection>
                        <div className="text-muted mb-1">Command</div>
                        <ToolOutput>{command}</ToolOutput>
                    </ToolBodySection>
                )}
                {outputText && (
                    <ToolBodySection divided={!!formattedInput || !!command}>
                        <div className="text-muted mb-1">Output</div>
                        <ToolOutput>{outputText}</ToolOutput>
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
