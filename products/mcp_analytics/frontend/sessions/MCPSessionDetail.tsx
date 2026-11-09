import { useActions, useValues } from 'kea'

import { IconBolt, IconClock, IconSparkles, IconUser } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { Button, Spinner } from '@posthog/quill-primitives'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT } from '../feedback/constants'
import { MCPAnalyticsFeedbackPrompt } from '../feedback/MCPAnalyticsFeedbackPrompt'
import { mcpSessionsLogic } from './mcpSessionsLogic'
import { MCPToolCallRow } from './MCPToolCallRow'
import { MCPToolCallRowShell } from './MCPToolCallRowShell'
import { formatDuration, sessionDurationMs, shortenSessionId } from './utils'

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

const MAX_TOOL_CALL_SKELETONS = 8

function ToolCallRowSkeletons({ count }: { count: number }): JSX.Element {
    return (
        <ol className="flex flex-col gap-2 list-none pl-0" aria-hidden>
            {Array.from({ length: count }, (_, i) => (
                <MCPToolCallRowShell key={i}>
                    <div className="flex h-4 items-center justify-between gap-2">
                        <LemonSkeleton className="h-3 w-32" />
                        <LemonSkeleton className="h-3 w-20" />
                    </div>
                    <div className="flex h-4 items-center pl-5">
                        <LemonSkeleton className="h-3 w-3/5" />
                    </div>
                </MCPToolCallRowShell>
            ))}
        </ol>
    )
}

function MCPSessionDetailSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col h-full min-h-0" aria-busy>
            <header className="flex flex-col gap-2 shrink-0 border-b border-primary px-3 pt-3 pb-2">
                <div className="flex items-center gap-2">
                    <LemonSkeleton.Circle className="h-9 w-9" />
                    <div className="flex flex-col flex-1 gap-1">
                        <LemonSkeleton className="h-4 w-40" />
                        <LemonSkeleton className="h-3 w-56" />
                    </div>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                    {['w-28', 'w-20', 'w-14', 'w-28'].map((width, i) => (
                        <LemonSkeleton key={i} className={`h-5 rounded-full ${width}`} />
                    ))}
                </div>
            </header>
            <section className="flex-1 min-h-0 overflow-hidden px-3 py-3">
                <ToolCallRowSkeletons count={4} />
            </section>
            <hr className="shrink-0 border-t border-primary my-0" />
            <footer className="shrink-0 px-3 py-3">
                <LemonSkeleton className="h-6 w-48" />
            </footer>
        </div>
    )
}

export function MCPSessionDetail(): JSX.Element {
    const {
        selectedSession,
        selectedSessionToolCalls,
        selectedSessionIntent,
        isSelectedSessionGenerating,
        dateFilter,
        sessionsLoading,
    } = useValues(mcpSessionsLogic)
    const { generateIntent, loadMoreToolCalls, loadToolCalls } = useActions(mcpSessionsLogic)

    if (!selectedSession) {
        if (sessionsLoading) {
            return <MCPSessionDetailSkeleton />
        }
        return (
            <div className="flex h-full items-center justify-center text-sm text-secondary p-6 text-center">
                Pick a session to step through its tool calls.
            </div>
        )
    }

    const durationMs = sessionDurationMs(selectedSession.session_start, selectedSession.session_end)
    const calls = selectedSession.tool_calls
    const identifiedPerson = !!(selectedSession.person_name || selectedSession.person_email)
    const primaryLabel = identifiedPerson
        ? selectedSession.person_name || selectedSession.person_email || selectedSession.distinct_id
        : selectedSession.distinct_id || 'unknown'

    // The panel's view of the selected session's calls: the list, whether more pages exist, whether
    // the first page is still loading (skeleton), and whether a "Load more" append is in flight.
    const { calls: toolCalls, hasNext, loading, loadingMore, error } = selectedSessionToolCalls
    const skeletonCount = Math.min(calls || 1, MAX_TOOL_CALL_SKELETONS)

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
                        {selectedSession.distinct_id ? (
                            <CopyToClipboardInline
                                explicitValue={selectedSession.distinct_id}
                                description="distinct id"
                                iconSize="xsmall"
                                tooltipMessage={<IdTooltip label="Distinct ID" value={selectedSession.distinct_id} />}
                                className="truncate font-mono text-[11px] text-secondary"
                            >
                                {selectedSession.distinct_id}
                            </CopyToClipboardInline>
                        ) : null}
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                    {selectedSession.mcp_client_name ? (
                        <MetaBadge icon={<IconSparkles />} label={selectedSession.mcp_client_name} />
                    ) : null}
                    <MetaBadge icon={<IconBolt />} label={`${calls} tool call${calls === 1 ? '' : 's'}`} />
                    <MetaBadge icon={<IconClock />} label={formatDuration(durationMs)} />
                    <CopyToClipboardInline
                        explicitValue={selectedSession.session_id}
                        description="session id"
                        iconSize="xsmall"
                        tooltipMessage={<IdTooltip label="Session ID" value={selectedSession.session_id} />}
                        className="rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-secondary font-mono"
                    >
                        {shortenSessionId(selectedSession.session_id)}
                    </CopyToClipboardInline>
                </div>
            </header>

            <section className="flex-1 min-h-0 overflow-y-auto px-3 py-3">
                {loading ? (
                    <ToolCallRowSkeletons count={skeletonCount} />
                ) : error ? (
                    <div className="flex flex-col items-start gap-2 text-sm text-secondary">
                        Could not load this session's tool calls.
                        <LemonButton size="small" onClick={() => loadToolCalls(selectedSession.session_id)}>
                            Retry
                        </LemonButton>
                    </div>
                ) : toolCalls.length === 0 ? (
                    <div className="text-sm text-secondary">No tool calls captured for this session.</div>
                ) : (
                    <>
                        <ol className="flex flex-col gap-2 list-none pl-0">
                            {toolCalls.map((toolCall, idx) => (
                                <MCPToolCallRow
                                    key={toolCall.event_id || `${toolCall.timestamp}-${idx}`}
                                    toolCall={toolCall}
                                    sessionId={selectedSession.session_id}
                                    sessionStart={selectedSession.session_start}
                                    dateFilter={dateFilter}
                                />
                            ))}
                        </ol>
                        {hasNext ? (
                            <div className="flex justify-center pt-2" data-quill>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => loadMoreToolCalls(selectedSession.session_id)}
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

            <hr className="shrink-0 border-t border-primary my-0" />

            <footer className="shrink-0 bg-gradient-to-br from-accent/15 via-accent/5 to-surface-primary px-3 py-3">
                {selectedSessionIntent ? (
                    <>
                        <div className="flex items-center gap-2 mb-1.5">
                            <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/20 text-accent">
                                <IconSparkles className="text-xs" />
                            </div>
                            <span className="text-[10px] uppercase tracking-wider font-semibold text-accent">
                                Session intent
                            </span>
                        </div>
                        <p className="text-xs leading-relaxed text-default">{selectedSessionIntent}</p>
                    </>
                ) : (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.McpAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            icon={<IconSparkles />}
                            loading={isSelectedSessionGenerating}
                            onClick={() => generateIntent(selectedSession.session_id)}
                        >
                            {isSelectedSessionGenerating ? 'Thinking…' : 'Summarize session intent'}
                        </LemonButton>
                    </AccessControlAction>
                )}
            </footer>
            {!loading && toolCalls.length > 0 && (
                <MCPAnalyticsFeedbackPrompt
                    contextKey={selectedSession.session_id}
                    prompt={MCP_ANALYTICS_SESSION_FEEDBACK_PROMPT}
                />
            )}
        </div>
    )
}
