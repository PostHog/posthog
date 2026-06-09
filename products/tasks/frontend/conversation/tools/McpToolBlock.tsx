import { JSX, useState } from 'react'

import { IconBolt } from '../primitives/icons'
import {
    compactInput,
    ExpandableIcon,
    ExpandedContentBox,
    formatInput,
    getContentText,
    StatusIndicators,
    stripCodeFences,
    ToolTitle,
    ToolViewProps,
    useToolCallStatus,
} from '../primitives/toolCallUtils'

interface McpToolBlockProps extends ToolViewProps {
    mcpToolName: string
}

/** Splits an `mcp__<server>__<tool>` key into its server and tool parts. */
function parseMcpToolKey(mcpToolName: string): { serverName: string; toolName: string } {
    const parts = mcpToolName.split('__')
    return {
        serverName: parts[1] ?? '',
        toolName: parts.slice(2).join('__'),
    }
}

/**
 * Read-only renderer for `mcp__*` tool calls. Shows the server/tool name as a
 * one-line title with a compact input preview; clicking expands the full input
 * and (when complete) the tool output. The live MCP UI iframe host from the
 * desktop app is intentionally omitted — this transcript renders results
 * statically only.
 */
export function McpToolBlock({
    toolCall,
    turnCancelled,
    turnComplete,
    mcpToolName,
    expanded = false,
}: McpToolBlockProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(expanded)
    const { status, rawInput, content } = toolCall
    const { isLoading, isFailed, wasCancelled, isComplete } = useToolCallStatus(status, turnCancelled, turnComplete)

    const { serverName, toolName } = parseMcpToolKey(mcpToolName)
    const inputPreview = compactInput(rawInput)
    const fullInput = formatInput(rawInput)

    const output = stripCodeFences(getContentText(content) ?? '')
    const hasOutput = output.trim().length > 0
    const isExpandable = !!fullInput || hasOutput

    const handleClick = (): void => {
        if (isExpandable) {
            setIsExpanded(!isExpanded)
        }
    }

    return (
        <div className={`group py-0.5 ${isExpandable ? 'cursor-pointer' : ''}`} onClick={handleClick}>
            <div className="flex gap-2">
                <div className="shrink-0 pt-px">
                    <ExpandableIcon
                        icon={IconBolt}
                        isLoading={isLoading}
                        isExpandable={isExpandable}
                        isExpanded={isExpanded}
                    />
                </div>
                <div className="flex min-w-0 flex-wrap items-center gap-1">
                    <ToolTitle>
                        <span className="text-muted">{serverName}</span>
                        {' - '}
                        {toolName}
                        <span className="text-muted">{' (MCP)'}</span>
                    </ToolTitle>
                    {inputPreview && (
                        <ToolTitle>
                            <span className="text-accent">{inputPreview}</span>
                        </ToolTitle>
                    )}
                    <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
                </div>
            </div>

            {isExpanded && (
                <>
                    {fullInput && <ExpandedContentBox>{fullInput}</ExpandedContentBox>}
                    {isComplete && hasOutput && <ExpandedContentBox>{output}</ExpandedContentBox>}
                </>
            )}
        </div>
    )
}
