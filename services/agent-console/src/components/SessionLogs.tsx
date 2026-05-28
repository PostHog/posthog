/**
 * `<SessionLogs />` — system-level log entries for a session, the
 * "what was the runtime doing" view that sits next to the
 * trigger-shaped playback.
 *
 * Each row: level dot + service + relative-to-session-start
 * timestamp + message + collapsed structured fields. Click a row
 * with a `call_id` field to cross-link the playback's matching
 * tool-call card.
 *
 * v0 fixture-driven; v0.1 sources from PostHog logs product
 * filtered by `session_id`. The shape — pino-style structured logs
 * with `session_id` correlation — matches what the agent services
 * already emit, so no platform change needed.
 */

'use client'

import { ChevronDownIcon, ChevronRightIcon } from 'lucide-react'
import { useState } from 'react'

import { JsonView } from '@posthog/agent-chat'
import type { LogEntry, LogLevel } from '@posthog/agent-chat/fixtures'

export interface SessionLogsProps {
    logs: LogEntry[]
    /** Cross-link: highlight the row whose `fields.call_id` matches. */
    highlightedCallId?: string | null
    /** Click handler — fires when user clicks a row that carries a call_id. */
    onSelectCallId?: (callId: string) => void
    /** Reference timestamp for relative formatting (typically session.started_at). */
    sessionStartedAt?: string
}

export function SessionLogs({
    logs,
    highlightedCallId,
    onSelectCallId,
    sessionStartedAt,
}: SessionLogsProps): React.ReactElement {
    return (
        <div className="flex h-full flex-col overflow-hidden rounded-md border border-border bg-background">
            <div className="flex h-9 items-center gap-2 border-b border-border bg-muted/20 px-4 text-xs">
                <span className="font-medium uppercase tracking-wide text-muted-foreground">Logs</span>
                <span className="text-muted-foreground">·</span>
                <span className="font-mono text-[0.6875rem] text-muted-foreground">
                    {logs.length} {logs.length === 1 ? 'entry' : 'entries'}
                </span>
                <span className="ml-auto text-[0.6875rem] text-muted-foreground">filtered by session_id</span>
            </div>

            {logs.length === 0 ? (
                <div className="flex flex-1 items-center justify-center px-4 py-8 text-center text-xs text-muted-foreground">
                    No logs for this session yet.
                </div>
            ) : (
                <ul className="flex-1 divide-y divide-border/60 overflow-y-auto font-mono text-[0.6875rem]">
                    {logs.map((entry, i) => (
                        <li key={`${entry.ts}-${i}`}>
                            <LogRow
                                entry={entry}
                                referenceTs={sessionStartedAt ?? logs[0]?.ts}
                                highlighted={isHighlighted(entry, highlightedCallId)}
                                onSelectCallId={onSelectCallId}
                            />
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}

function isHighlighted(entry: LogEntry, callId?: string | null): boolean {
    if (!callId) {
        return false
    }
    const value = entry.fields?.call_id
    return typeof value === 'string' && value === callId
}

/* ── Row ─────────────────────────────────────────────────────────── */

function LogRow({
    entry,
    referenceTs,
    highlighted,
    onSelectCallId,
}: {
    entry: LogEntry
    referenceTs?: string
    highlighted: boolean
    onSelectCallId?: (callId: string) => void
}): React.ReactElement {
    const [open, setOpen] = useState(false)
    const tone = levelTone(entry.level)
    const callId = typeof entry.fields?.call_id === 'string' ? entry.fields.call_id : null
    const fieldEntries = Object.entries(entry.fields ?? {}).filter(([k]) => k !== 'session_id')
    const hasFields = fieldEntries.length > 0

    return (
        <div
            className={'transition-colors ' + (highlighted ? 'bg-info/10' : '')}
            data-call-id={callId ?? undefined}
            id={callId ? `log-${callId}` : undefined}
        >
            <button
                type="button"
                onClick={() => {
                    if (hasFields) {
                        setOpen((o) => !o)
                    }
                    if (callId) {
                        onSelectCallId?.(callId)
                    }
                }}
                className={
                    (hasFields || callId ? 'cursor-pointer hover:bg-accent/40' : 'cursor-default') +
                    ' flex w-full items-baseline gap-2 px-3 py-1.5 text-left'
                }
            >
                <span
                    className={`inline-flex h-1.5 w-1.5 shrink-0 self-center rounded-full ${tone.dotClass}`}
                    aria-hidden
                />
                <span className="w-12 shrink-0 text-right text-muted-foreground/70">
                    {formatRelative(entry.ts, referenceTs)}
                </span>
                <span className={`w-14 shrink-0 uppercase ${tone.labelClass}`}>{entry.level}</span>
                <span className="w-16 shrink-0 truncate text-muted-foreground">{entry.service}</span>
                <span className="min-w-0 flex-1 truncate text-foreground">{entry.message}</span>
                {hasFields ? (
                    open ? (
                        <ChevronDownIcon className="h-3 w-3 shrink-0 self-center text-muted-foreground" />
                    ) : (
                        <ChevronRightIcon className="h-3 w-3 shrink-0 self-center text-muted-foreground" />
                    )
                ) : null}
            </button>

            {open && hasFields ? (
                <div className="border-t border-border/40 px-3 py-2">
                    <JsonView value={Object.fromEntries(fieldEntries)} expandToLevel={2} />
                </div>
            ) : null}
        </div>
    )
}

/* ── Helpers ─────────────────────────────────────────────────────── */

function levelTone(level: LogLevel): { dotClass: string; labelClass: string } {
    switch (level) {
        case 'fatal':
        case 'error':
            return { dotClass: 'bg-destructive', labelClass: 'text-destructive' }
        case 'warn':
            return { dotClass: 'bg-warning', labelClass: 'text-warning-foreground' }
        case 'info':
            return { dotClass: 'bg-info', labelClass: 'text-info-foreground' }
        case 'debug':
        default:
            return { dotClass: 'bg-muted-foreground/40', labelClass: 'text-muted-foreground' }
    }
}

function formatRelative(ts: string, referenceTs?: string): string {
    if (!referenceTs) {
        return formatClock(ts)
    }
    const delta = new Date(ts).getTime() - new Date(referenceTs).getTime()
    if (Number.isNaN(delta) || delta < 0) {
        return formatClock(ts)
    }
    if (delta < 1000) {
        return `+${delta}ms`
    }
    if (delta < 60_000) {
        return `+${(delta / 1000).toFixed(1)}s`
    }
    const m = Math.floor(delta / 60_000)
    const s = Math.floor((delta % 60_000) / 1000)
    return `+${m}m${s.toString().padStart(2, '0')}`
}

function formatClock(ts: string): string {
    return new Date(ts).toLocaleString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
