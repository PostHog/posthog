import { useActions, useValues } from 'kea'

import { IconBolt, IconClock, IconSparkles, IconUser, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import { Button, Spinner } from '@posthog/quill-primitives'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { mcpSessionsLogic } from './mcpSessionsLogic'
import { formatDuration, formatRelativeOffset, sessionDurationMs, shortenSessionId } from './utils'

function MetaBadge({ icon, label }: { icon: React.ReactNode; label: React.ReactNode }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-secondary">
            <span className="text-[11px] leading-none">{icon}</span>
            {label}
        </span>
    )
}

export function MCPSessionDetail(): JSX.Element {
    const {
        selectedSession,
        toolCalls,
        isSelectedSessionToolCallsLoading,
        toolCallsHasNext,
        toolCallsLoadingMore,
        selectedSessionIntent,
        isSelectedSessionGenerating,
    } = useValues(mcpSessionsLogic)
    const { generateIntent, loadMoreToolCalls } = useActions(mcpSessionsLogic)

    if (!selectedSession) {
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

    // Skeleton the panel only while the *selected* session's first page loads; a "Load more"
    // append keeps the existing calls and spins just the button. Scoped to the selected session
    // so a concurrent load-more for a previous session can't drop the skeleton early.
    const loading = isSelectedSessionToolCallsLoading

    return (
        <div className="flex flex-col h-full min-h-0">
            <header className="flex flex-col gap-2 shrink-0 border-b border-primary px-3 pt-3 pb-2">
                <div className="flex items-center gap-2 min-w-0">
                    {loading ? (
                        <LemonSkeleton.Circle className="h-9 w-9" />
                    ) : (
                        <div
                            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
                                identifiedPerson ? 'bg-accent/20 text-accent' : 'bg-surface-secondary text-secondary'
                            }`}
                        >
                            <IconUser className="text-2xl" />
                        </div>
                    )}
                    <div className="flex flex-col min-w-0 flex-1 gap-1">
                        {loading ? (
                            <>
                                <LemonSkeleton className="h-4 w-40" />
                                <LemonSkeleton className="h-3 w-28" />
                            </>
                        ) : (
                            <>
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
                                        className="truncate font-mono text-[11px] text-secondary"
                                    >
                                        {selectedSession.distinct_id}
                                    </CopyToClipboardInline>
                                ) : null}
                            </>
                        )}
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                    {loading ? (
                        <LemonSkeleton repeat={4} className="h-5 w-20 rounded-full" />
                    ) : (
                        <>
                            {selectedSession.mcp_client_name ? (
                                <MetaBadge icon={<IconSparkles />} label={selectedSession.mcp_client_name} />
                            ) : null}
                            <MetaBadge icon={<IconBolt />} label={`${calls} tool call${calls === 1 ? '' : 's'}`} />
                            <MetaBadge icon={<IconClock />} label={formatDuration(durationMs)} />
                            <Tooltip
                                title={
                                    <div className="max-w-xs break-all">
                                        Session ID: <span className="font-mono">{selectedSession.session_id}</span>
                                    </div>
                                }
                            >
                                <span className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-secondary font-mono">
                                    <CopyToClipboardInline
                                        explicitValue={selectedSession.session_id}
                                        description="session id"
                                        iconSize="xsmall"
                                        className="font-mono"
                                    >
                                        {shortenSessionId(selectedSession.session_id)}
                                    </CopyToClipboardInline>
                                </span>
                            </Tooltip>
                        </>
                    )}
                </div>
            </header>

            <section className="flex-1 min-h-0 overflow-y-auto px-3 py-3">
                {loading ? (
                    <div className="flex flex-col gap-2">
                        <LemonSkeleton repeat={3} className="h-16 w-full" />
                    </div>
                ) : toolCalls.length === 0 ? (
                    <div className="text-sm text-secondary">No tool calls captured for this session.</div>
                ) : (
                    <>
                        <ol className="flex flex-col gap-2 list-none pl-0">
                            {toolCalls.map((toolCall, idx) => (
                                <li
                                    key={toolCall.event_id || `${toolCall.timestamp}-${idx}`}
                                    className={`relative flex flex-col gap-1 rounded border bg-surface-primary px-2 py-1.5 transition-colors hover:bg-surface-secondary ${
                                        toolCall.is_error
                                            ? 'border-danger border-l-2'
                                            : 'border-primary border-l-2 border-l-accent/60'
                                    }`}
                                >
                                    <div className="flex items-center justify-between gap-2 text-xs">
                                        <div className="flex items-center gap-1.5 min-w-0">
                                            {toolCall.is_error ? (
                                                <IconWarning className="text-danger shrink-0 text-xs" />
                                            ) : (
                                                <IconBolt className="text-accent shrink-0 text-xs" />
                                            )}
                                            <span className="font-mono font-semibold truncate">
                                                {toolCall.tool_name || 'unknown'}
                                            </span>
                                            {toolCall.is_error ? (
                                                <LemonTag type="danger" size="small">
                                                    error
                                                </LemonTag>
                                            ) : null}
                                        </div>
                                        <div className="flex items-center gap-2 text-secondary whitespace-nowrap font-mono text-[11px]">
                                            {toolCall.duration_ms != null ? (
                                                <span>{formatDuration(toolCall.duration_ms)} ·</span>
                                            ) : null}
                                            <span>
                                                {formatRelativeOffset(
                                                    selectedSession.session_start,
                                                    toolCall.timestamp
                                                )}
                                            </span>
                                        </div>
                                    </div>

                                    <div className="text-xs leading-snug pl-5">
                                        {toolCall.intent || (
                                            <span className="text-secondary italic">No intent captured.</span>
                                        )}
                                    </div>

                                    {toolCall.is_error && toolCall.error_message ? (
                                        <div className="text-xs text-danger font-mono pl-5 break-all">
                                            {toolCall.error_message}
                                        </div>
                                    ) : null}
                                </li>
                            ))}
                        </ol>
                        {toolCallsHasNext ? (
                            <div className="flex justify-center pt-2" data-quill>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => loadMoreToolCalls()}
                                    disabled={toolCallsLoadingMore}
                                    data-attr="mcp-session-load-more-tool-calls"
                                >
                                    {toolCallsLoadingMore ? <Spinner /> : null}
                                    Load more
                                </Button>
                            </div>
                        ) : null}
                    </>
                )}
            </section>

            <hr className="shrink-0 border-t border-primary my-0" />

            <footer className="shrink-0 bg-gradient-to-br from-accent/15 via-accent/5 to-surface-primary px-3 py-3">
                {loading ? (
                    <LemonSkeleton className="h-7 w-48" />
                ) : selectedSessionIntent ? (
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
                    <LemonButton
                        type="primary"
                        size="xsmall"
                        icon={<IconSparkles />}
                        loading={isSelectedSessionGenerating}
                        onClick={() => generateIntent(selectedSession.session_id)}
                    >
                        {isSelectedSessionGenerating ? 'Thinking…' : 'Summarize session intent'}
                    </LemonButton>
                )}
            </footer>
        </div>
    )
}
