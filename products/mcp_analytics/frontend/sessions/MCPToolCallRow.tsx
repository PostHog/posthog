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
import { MCPErrorContext, formatCapturedJson, formatErrorContext } from '../tool-quality/errorContext'
import { MCPToolCallRowShell } from './MCPToolCallRowShell'
import { formatDuration, formatRelativeOffset } from './utils'

function errorContext(toolCall: MCPToolCallApi, sessionId: string): MCPErrorContext {
    return {
        toolName: toolCall.tool_name,
        errorType: toolCall.error_type || 'unknown',
        errorStatus: toolCall.error_status || undefined,
        errorMessage: toolCall.error_message || undefined,
        errorCode: toolCall.error_code || undefined,
        errorField: toolCall.error_field || undefined,
        timestamp: toolCall.timestamp,
        intent: toolCall.intent || undefined,
        sessionId,
        parameters: toolCall.parameters || undefined,
        response: toolCall.response || undefined,
    }
}

function CapturedJson({
    label,
    json,
    property,
    names = [],
}: {
    label: string
    json: string
    property: string
    names?: readonly string[]
}): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <span className="text-[11px] font-semibold text-secondary">{label}</span>
            {json ? (
                <CodeSnippet
                    language={Language.JSON}
                    compact
                    wrap
                    thing={label.toLowerCase()}
                    maxLinesWithoutExpansion={12}
                >
                    {formatCapturedJson(json)}
                </CodeSnippet>
            ) : names.length > 0 ? (
                <span className="text-xs text-secondary">
                    Values not captured. Argument names: <span className="font-mono">{names.join(', ')}</span>
                </span>
            ) : (
                <span className="text-xs text-secondary">Not captured. The SDK sends this as {property}.</span>
            )}
        </div>
    )
}

function FailureDetails({ toolCall }: { toolCall: MCPToolCallApi }): JSX.Element | null {
    const details = [
        toolCall.error_code ? `Code ${toolCall.error_code}` : null,
        toolCall.error_field ? `Argument ${toolCall.error_field}` : null,
    ].filter(Boolean)
    return details.length > 0 ? (
        <div className="text-[11px] text-secondary font-mono pl-5 break-all">{details.join(' · ')}</div>
    ) : null
}

function MCPToolCallDetails({ toolCall, sessionId }: { toolCall: MCPToolCallApi; sessionId: string }): JSX.Element {
    const failure = toolCall.is_error && toolCall.tool_name ? errorContext(toolCall, sessionId) : null

    return (
        <div className="flex flex-col gap-2 pl-5 pt-1">
            <CapturedJson
                label="Arguments"
                json={toolCall.parameters}
                property="$mcp_parameters"
                names={toolCall.input_keys}
            />
            <CapturedJson label="Result" json={toolCall.response} property="$mcp_response" />
            {toolCall.llm_model ? (
                <span className="text-xs text-secondary">
                    Model: <span className="font-mono">{toolCall.llm_model}</span>
                </span>
            ) : null}
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
                {failure ? (
                    <>
                        <LemonButton
                            size="xsmall"
                            icon={<IconCopy />}
                            tooltip="Copy the failure, arguments, result and links for a coding agent"
                            onClick={() => void copyToClipboard(formatErrorContext(failure), 'error context')}
                            data-attr="mcp-session-tool-call-copy-context"
                        >
                            Copy context
                        </LemonButton>
                        <CreateFixTaskButton context={failure} />
                    </>
                ) : null}
            </div>
        </div>
    )
}

// A resolved exec `call` already carries the inner tool's name; other commands stay `exec`.
function execCommandLabel({ tool_name, exec_verb, exec_target_tool }: MCPToolCallApi): string | null {
    if (tool_name !== 'exec' || !exec_verb) {
        return null
    }
    if (exec_verb === 'unrecognized') {
        return 'unrecognized command'
    }
    return exec_target_tool === 'unrecognized'
        ? `${exec_verb} unknown tool`
        : [exec_verb, exec_target_tool].filter(Boolean).join(' ')
}

function MCPToolCallTitle({ toolCall, dateFilter }: { toolCall: MCPToolCallApi; dateFilter: DateFilter }): JSX.Element {
    return (
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
            {execCommandLabel(toolCall) ? (
                <span className="font-mono text-secondary truncate">{execCommandLabel(toolCall)}</span>
            ) : null}
            {toolCall.is_error ? (
                <LemonTag type="danger" size="small">
                    error
                </LemonTag>
            ) : null}
        </div>
    )
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
        <MCPToolCallRowShell isError={toolCall.is_error}>
            <div className="flex items-center justify-between gap-2 text-xs">
                <MCPToolCallTitle toolCall={toolCall} dateFilter={dateFilter} />
                <div className="flex items-center gap-2 text-secondary whitespace-nowrap font-mono text-[11px]">
                    {toolCall.duration_ms != null ? <span>{formatDuration(toolCall.duration_ms)} ·</span> : null}
                    <span>{formatRelativeOffset(sessionStart, toolCall.timestamp)}</span>
                    <LemonButton
                        size="xsmall"
                        noPadding
                        icon={<IconChevronDown className={expanded ? 'rotate-180' : undefined} />}
                        onClick={() => setExpanded(!expanded)}
                        aria-expanded={expanded}
                        tooltip={expanded ? 'Hide details' : 'Show arguments, result and actions'}
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
            {toolCall.is_error ? <FailureDetails toolCall={toolCall} /> : null}

            {expanded ? <MCPToolCallDetails toolCall={toolCall} sessionId={sessionId} /> : null}
        </MCPToolCallRowShell>
    )
}
