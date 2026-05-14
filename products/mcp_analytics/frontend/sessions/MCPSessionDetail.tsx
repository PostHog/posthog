import { useValues } from 'kea'

import { IconBolt, IconClock, IconSparkles, IconUser, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { humanFriendlyDuration, midEllipsis } from 'lib/utils'

import { mcpSessionsLogic } from './mcpSessionsLogic'
import { relativeOffset, sessionDurationMs } from './utils'

function MetaBadge({ icon, label }: { icon: React.ReactNode; label: React.ReactNode }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-secondary">
            <span className="text-[11px] leading-none">{icon}</span>
            {label}
        </span>
    )
}

export function MCPSessionDetail(): JSX.Element {
    const { selectedSession, toolCalls, toolCallsLoading, toolCallsTruncated } = useValues(mcpSessionsLogic)

    if (!selectedSession) {
        return (
            <div className="flex h-full items-center justify-center text-sm text-secondary p-6 text-center">
                Pick a session on the left to step through its tool calls.
            </div>
        )
    }

    const durationMs = sessionDurationMs(selectedSession.first_seen, selectedSession.last_seen)
    const calls = selectedSession.event_count
    const identifiedPerson = !!selectedSession.person_id
    const primaryLabel = identifiedPerson
        ? selectedSession.person_name || selectedSession.person_email || selectedSession.distinct_id
        : selectedSession.distinct_id || 'unknown'

    return (
        <div className="flex flex-col gap-2">
            <header className="flex flex-col gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <div
                        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${
                            identifiedPerson ? 'bg-accent/20 text-accent' : 'bg-surface-secondary text-secondary'
                        }`}
                    >
                        <IconUser className="text-2xl" />
                    </div>
                    <div className="flex flex-col min-w-0 flex-1">
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
                    </div>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                    {selectedSession.mcp_client_name ? (
                        <MetaBadge icon={<IconSparkles />} label={selectedSession.mcp_client_name} />
                    ) : null}
                    <MetaBadge icon={<IconBolt />} label={`${calls} tool call${calls === 1 ? '' : 's'}`} />
                    <MetaBadge
                        icon={<IconClock />}
                        label={humanFriendlyDuration(durationMs / 1000, { secondsFixed: 1 })}
                    />
                    <span
                        className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-[11px] text-secondary font-mono"
                        title={selectedSession.session_id}
                    >
                        <CopyToClipboardInline
                            explicitValue={selectedSession.session_id}
                            description="session id"
                            iconSize="xsmall"
                            className="font-mono"
                        >
                            {midEllipsis(selectedSession.session_id, 13)}
                        </CopyToClipboardInline>
                    </span>
                </div>
            </header>

            <hr className="border-t border-primary -mx-3" />

            <section className="flex flex-col gap-2">
                {toolCallsTruncated ? (
                    <LemonBanner type="warning">
                        Showing the first 500 tool calls in this window. Narrow the date range to surface every event.
                    </LemonBanner>
                ) : null}
                {toolCallsLoading && toolCalls.length === 0 ? (
                    <div className="flex flex-col gap-2">
                        {[0, 1, 2].map((i) => (
                            <LemonSkeleton key={i} className="h-16 w-full" />
                        ))}
                    </div>
                ) : toolCalls.length === 0 ? (
                    <div className="text-sm text-secondary">No tool calls captured for this session.</div>
                ) : (
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
                                            <span>
                                                {humanFriendlyDuration(toolCall.duration_ms / 1000, {
                                                    secondsFixed: 1,
                                                })}{' '}
                                                ·
                                            </span>
                                        ) : null}
                                        <span>{relativeOffset(selectedSession.first_seen, toolCall.timestamp)}</span>
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
                )}
            </section>
        </div>
    )
}
