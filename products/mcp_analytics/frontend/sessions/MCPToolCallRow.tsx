import { useState } from 'react'

import { IconBolt, IconChevronDown, IconCopy, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { MCPToolCallApi } from '../generated/api.schemas'
import { DateFilter, mcpToolReportUrl } from '../mcpAnalyticsToolQualityLogic'
import { CreateFixTaskButton } from '../tool-quality/CreateFixTaskButton'
import { MCPErrorContext, formatErrorContext, formatToolArguments } from '../tool-quality/errorContext'
import { formatDuration, formatRelativeOffset } from './utils'

function errorContext(toolCall: MCPToolCallApi, sessionId: string): MCPErrorContext {
    return {
        toolName: toolCall.tool_name,
        errorType: toolCall.error_type || 'unknown',
        errorStatus: toolCall.error_status || undefined,
        errorMessage: toolCall.error_message || undefined,
        timestamp: toolCall.timestamp,
        intent: toolCall.intent || undefined,
        sessionId,
        parameters: toolCall.parameters || undefined,
    }
}

export function MCPToolCallRow({
    toolCall,
    sessionId,
    sessionStart,
    dateFilter,
}: {
    toolCall: MCPToolCallApi
    sessionId: string
    sessionStart: string
    dateFilter: DateFilter
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)

    return (
        <li
            className={`relative flex flex-col gap-1 rounded border bg-surface-primary px-2 py-1.5 ${
                toolCall.is_error ? 'border-danger border-l-2' : 'border-primary border-l-2 border-l-accent/60'
            }`}
        >
            <div className="flex items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-1.5 min-w-0">
                    {toolCall.is_error ? (
                        <IconWarning className="text-danger shrink-0 text-xs" />
                    ) : (
                        <IconBolt className="text-accent shrink-0 text-xs" />
                    )}
                    {toolCall.tool_name ? (
                        <Link
                            to={mcpToolReportUrl(toolCall.tool_name, dateFilter)}
                            className="font-mono font-semibold truncate"
                            tooltip="Open this tool's report"
                        >
                            {toolCall.tool_name}
                        </Link>
                    ) : (
                        <span className="font-mono font-semibold truncate">unknown</span>
                    )}
                    {toolCall.is_error ? (
                        <LemonTag type="danger" size="small">
                            error
                        </LemonTag>
                    ) : null}
                </div>
                <div className="flex items-center gap-2 text-secondary whitespace-nowrap font-mono text-[11px]">
                    {toolCall.duration_ms != null ? <span>{formatDuration(toolCall.duration_ms)} ·</span> : null}
                    <span>{formatRelativeOffset(sessionStart, toolCall.timestamp)}</span>
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconChevronDown className={expanded ? 'rotate-180' : undefined} />}
                        onClick={() => setExpanded(!expanded)}
                        aria-expanded={expanded}
                        tooltip={expanded ? 'Hide details' : 'Show arguments and actions'}
                        data-attr="mcp-session-tool-call-expand"
                    />
                </div>
            </div>

            <div className="text-xs leading-snug pl-5">
                {toolCall.intent || <span className="text-secondary italic">No intent captured.</span>}
            </div>

            {toolCall.is_error && toolCall.error_message ? (
                <div className="text-xs text-danger font-mono pl-5 break-all">{toolCall.error_message}</div>
            ) : null}

            {expanded ? (
                <div className="flex flex-col gap-2 pl-5 pt-1">
                    {toolCall.parameters ? (
                        <CodeSnippet language={Language.JSON} compact thing="arguments" maxLinesWithoutExpansion={12}>
                            {formatToolArguments(toolCall.parameters)}
                        </CodeSnippet>
                    ) : (
                        <div className="text-xs text-secondary">
                            No arguments captured. The SDK sends them as $mcp_parameters.
                        </div>
                    )}
                    <div className="flex flex-wrap items-center gap-1">
                        {toolCall.event_id ? (
                            <LemonButton
                                size="xsmall"
                                to={urls.event(toolCall.event_id, toolCall.timestamp)}
                                data-attr="mcp-session-tool-call-view-event"
                            >
                                View event
                            </LemonButton>
                        ) : null}
                        {toolCall.is_error ? (
                            <>
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconCopy />}
                                    tooltip="Copy the failure, arguments and links for a coding agent"
                                    onClick={() =>
                                        void copyToClipboard(
                                            formatErrorContext(errorContext(toolCall, sessionId)),
                                            'error context'
                                        )
                                    }
                                    data-attr="mcp-session-tool-call-copy-context"
                                >
                                    Copy context
                                </LemonButton>
                                <CreateFixTaskButton context={errorContext(toolCall, sessionId)} />
                            </>
                        ) : null}
                    </div>
                </div>
            ) : null}
        </li>
    )
}
