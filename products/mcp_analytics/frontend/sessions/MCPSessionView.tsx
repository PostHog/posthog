import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconBolt, IconClock, IconSparkles, IconUser } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Button, Spinner } from '@posthog/quill-primitives'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT } from '../feedback/constants'
import { MCPAnalyticsFeedbackPrompt } from '../feedback/MCPAnalyticsFeedbackPrompt'
import { MCPSessionApi, MCPToolCallApi } from '../generated/api.schemas'
import { MCPToolCallRow } from './MCPToolCallRow'
import { MissingCapabilityRow } from './MissingCapabilityRow'
import { SessionIntentCard } from './SessionIntentCard'
import { MissingCapabilityReport, sessionMissingCapabilitiesLogic } from './sessionMissingCapabilitiesLogic'
import { ToolCallRowSkeletons } from './ToolCallRowSkeletons'
import { formatDuration, sessionDurationMs, shortenSessionId } from './utils'

export interface MCPSessionToolCallsState {
    calls: MCPToolCallApi[]
    hasNext: boolean
    /** The first page is still loading. */
    loading: boolean
    /** A "Load more" append is in flight. */
    loadingMore: boolean
    error: boolean
}

export interface MCPSessionViewProps {
    session: MCPSessionApi
    toolCalls: MCPSessionToolCallsState
    intent: string
    isGeneratingIntent: boolean
    onGenerateIntent: () => void
    onLoadMoreToolCalls: () => void
    onRetryToolCalls: () => void
    /** Opened and scrolled into view. */
    focusedEventId?: string | null
    /** Highlighted. */
    focusedReport?: string | null
    /** Opens a call's event in a drawer. Without it, View event goes to the event page. */
    onOpenToolCall?: (toolCall: MCPToolCallApi, toolCalls: MCPToolCallApi[]) => void
}

const MAX_TOOL_CALL_SKELETONS = 8

type TimelineItem =
    | { kind: 'call'; toolCall: MCPToolCallApi; index: number }
    | { kind: 'report' | 'suggestion'; report: MissingCapabilityReport }

const timeOf = (timestamp: string): number => new Date(timestamp).getTime()

const callKey = ({ toolCall, index }: { toolCall: MCPToolCallApi; index: number }): string =>
    toolCall.event_id || `${toolCall.timestamp}-${index}`

/** Calls and reports by time; a report past the last loaded call waits. */
export function sessionTimeline(
    toolCalls: MCPToolCallApi[],
    reports: MissingCapabilityReport[],
    hasMoreCalls: boolean
): TimelineItem[] {
    const lastCallTime = toolCalls.length > 0 ? timeOf(toolCalls[toolCalls.length - 1].timestamp) : -Infinity
    const shownReports = hasMoreCalls ? reports.filter((report) => timeOf(report.timestamp) <= lastCallTime) : reports
    const items: TimelineItem[] = toolCalls.map((toolCall, index) => ({ kind: 'call', toolCall, index }))
    for (const report of shownReports) {
        const at = items.findIndex(
            (item) => item.kind === 'call' && timeOf(item.toolCall.timestamp) > timeOf(report.timestamp)
        )
        // The agent's suggested fix comes in the same report, so it follows right after it.
        const entries: TimelineItem[] = [{ kind: 'report', report }]
        if (report.suggestion) {
            entries.push({ kind: 'suggestion', report })
        }
        items.splice(at < 0 ? items.length : at, 0, ...entries)
    }
    return items
}

function MetaBadge({ icon, label }: { icon: React.ReactNode; label: React.ReactNode }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-secondary">
            <span className="text-[11px] leading-none">{icon}</span>
            {label}
        </span>
    )
}

function IdTooltip({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="max-w-xs break-all">
            {label}: <span className="font-mono">{value}</span>
            <div className="mt-1 opacity-75">Click to copy</div>
        </div>
    )
}

export function MCPSessionView({
    session,
    toolCalls: { calls: toolCalls, hasNext, loading, loadingMore, error },
    intent,
    isGeneratingIntent,
    onGenerateIntent,
    onLoadMoreToolCalls,
    onRetryToolCalls,
    focusedEventId,
    focusedReport,
    onOpenToolCall,
}: MCPSessionViewProps): JSX.Element {
    const durationMs = sessionDurationMs(session.session_start, session.session_end)
    const calls = session.tool_calls
    const identifiedPerson = !!(session.person_name || session.person_email)
    const primaryLabel = identifiedPerson
        ? session.person_name || session.person_email || session.distinct_id
        : session.distinct_id || 'unknown'
    const skeletonCount = Math.min(calls || 1, MAX_TOOL_CALL_SKELETONS)
    // One call open at a time, so stepping through calls doesn't stack open details.
    const [openCallKey, setOpenCallKey] = useState<string | null>(focusedEventId ?? null)
    useEffect(() => setOpenCallKey(focusedEventId ?? null), [focusedEventId])
    const { reports } = useValues(
        sessionMissingCapabilitiesLogic({
            sessionId: session.session_id,
            sessionStart: session.session_start,
            sessionEnd: session.session_end,
        })
    )
    const timeline = useMemo(() => sessionTimeline(toolCalls, reports, hasNext), [toolCalls, reports, hasNext])

    return (
        <div className="flex flex-col h-full min-h-0">
            <header className="flex flex-col gap-2 shrink-0 border-b border-primary px-3 pt-3 pb-2">
                <div className="flex items-center gap-2 min-w-0">
                    <div
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
                            identifiedPerson ? 'bg-accent/20 text-accent' : 'bg-surface-secondary text-secondary'
                        }`}
                    >
                        <IconUser className="text-2xl" />
                    </div>
                    <div className="flex flex-col min-w-0 flex-1 gap-1">
                        <span
                            className={`truncate font-semibold ${
                                identifiedPerson ? 'text-default text-sm' : 'font-mono text-xs text-secondary'
                            }`}
                        >
                            {primaryLabel}
                        </span>
                        {session.distinct_id ? (
                            <CopyToClipboardInline
                                explicitValue={session.distinct_id}
                                description="distinct id"
                                iconSize="xsmall"
                                tooltipMessage={<IdTooltip label="Distinct ID" value={session.distinct_id} />}
                                className="truncate font-mono text-[11px] text-secondary"
                            >
                                {session.distinct_id}
                            </CopyToClipboardInline>
                        ) : null}
                    </div>
                    {!intent && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.McpAnalytics}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                size="xsmall"
                                icon={<IconSparkles />}
                                loading={isGeneratingIntent}
                                onClick={onGenerateIntent}
                                className="shrink-0"
                                data-attr="mcp-session-summarize-intent"
                            >
                                {isGeneratingIntent ? 'Thinking…' : 'Summarize session intent'}
                            </LemonButton>
                        </AccessControlAction>
                    )}
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                    {session.mcp_client_name ? (
                        <MetaBadge icon={<IconSparkles />} label={session.mcp_client_name} />
                    ) : null}
                    <MetaBadge icon={<IconBolt />} label={`${calls} tool call${calls === 1 ? '' : 's'}`} />
                    <MetaBadge icon={<IconClock />} label={formatDuration(durationMs)} />
                    <CopyToClipboardInline
                        explicitValue={session.session_id}
                        description="session id"
                        iconSize="xsmall"
                        tooltipMessage={<IdTooltip label="Session ID" value={session.session_id} />}
                        className="rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-secondary font-mono"
                    >
                        {shortenSessionId(session.session_id)}
                    </CopyToClipboardInline>
                </div>
            </header>

            <section className="flex-1 min-h-0 overflow-y-auto px-3 py-3">
                {intent && (
                    <div className="mb-2">
                        <SessionIntentCard intent={intent} />
                    </div>
                )}
                {loading ? (
                    <ToolCallRowSkeletons count={skeletonCount} />
                ) : error ? (
                    <div className="flex flex-col items-start gap-2 text-sm text-secondary">
                        Could not load this session's tool calls.
                        <LemonButton size="small" onClick={onRetryToolCalls}>
                            Retry
                        </LemonButton>
                    </div>
                ) : toolCalls.length === 0 ? (
                    <div className="text-sm text-secondary">No tool calls captured for this session.</div>
                ) : (
                    <>
                        <ol className="flex flex-col gap-2 list-none pl-0">
                            {timeline.map((item) =>
                                item.kind === 'report' || item.kind === 'suggestion' ? (
                                    <MissingCapabilityRow
                                        key={`${item.kind}-${item.report.timestamp}-${item.report.report}`}
                                        report={item.report}
                                        sessionStart={session.session_start}
                                        variant={item.kind}
                                        focused={
                                            item.kind === 'report' &&
                                            !!focusedReport &&
                                            item.report.report === focusedReport
                                        }
                                    />
                                ) : (
                                    <MCPToolCallRow
                                        key={callKey(item)}
                                        toolCall={item.toolCall}
                                        sessionId={session.session_id}
                                        sessionStart={session.session_start}
                                        expanded={openCallKey === callKey(item)}
                                        onToggle={() =>
                                            setOpenCallKey(openCallKey === callKey(item) ? null : callKey(item))
                                        }
                                        focused={!!focusedEventId && item.toolCall.event_id === focusedEventId}
                                        onOpen={
                                            onOpenToolCall && item.toolCall.event_id
                                                ? () => onOpenToolCall(item.toolCall, toolCalls)
                                                : undefined
                                        }
                                    />
                                )
                            )}
                        </ol>
                        {hasNext ? (
                            <div className="flex justify-center pt-2" data-quill>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={onLoadMoreToolCalls}
                                    disabled={loadingMore}
                                    data-attr="mcp-session-load-more-tool-calls"
                                >
                                    {loadingMore ? <Spinner /> : null}
                                    Load more
                                </Button>
                            </div>
                        ) : null}
                    </>
                )}
            </section>

            {!loading && toolCalls.length > 0 && (
                <MCPAnalyticsFeedbackPrompt
                    contextKey={session.session_id}
                    prompt={MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT}
                />
            )}
        </div>
    )
}
