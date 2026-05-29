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
    // Tool calls correlate via the `id` field; older fixtures use `call_id`.
    const callId =
        (typeof entry.fields?.call_id === 'string' && entry.fields.call_id) ||
        (typeof entry.fields?.id === 'string' && entry.fields.id) ||
        null
    const fieldEntries = Object.entries(entry.fields ?? {}).filter(([k]) => k !== 'session_id')
    const hasFields = fieldEntries.length > 0
    const kindTone = kindToneFor(entry.service)
    const preview = previewFor(entry)

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
                <span
                    className={`w-14 shrink-0 rounded px-1.5 text-center text-[0.625rem] font-medium uppercase tracking-wide ${kindTone.badgeClass}`}
                >
                    {entry.service}
                </span>
                <span className="w-32 shrink-0 truncate font-medium text-foreground">{entry.message}</span>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{preview}</span>
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

/* ── Per-event preview + kind badge ──────────────────────────────── */

/**
 * Inline summary string for the row's "primary content" column.
 * Picks the most useful field per known event so the user gets the
 * gist without expanding. Falls back to a compact key=value dump.
 */
function previewFor(entry: LogEntry): string {
    const fields = entry.fields
    if (!fields) {
        return ''
    }
    const event = entry.message
    switch (event) {
        case 'assistant_text':
            return typeof fields.text === 'string' ? fields.text : ''
        case 'tool_call': {
            const name = typeof fields.name === 'string' ? fields.name : '?'
            const args =
                fields.args && typeof fields.args === 'object'
                    ? compactJson(fields.args as Record<string, unknown>, 60)
                    : ''
            return args ? `${name} ${args}` : name
        }
        case 'tool_result': {
            const name = typeof fields.name === 'string' ? fields.name : '?'
            const ok = fields.ok === true ? '✓' : fields.ok === false ? '✗' : ''
            return `${name} ${ok}`.trim()
        }
        case 'session_started': {
            const agent = typeof fields.agent === 'string' ? short(fields.agent) : ''
            const rev = typeof fields.rev === 'string' ? short(fields.rev) : ''
            return [agent && `agent=${agent}`, rev && `rev=${rev}`].filter(Boolean).join(' · ')
        }
        case 'turn_started':
            return typeof fields.turn === 'number' ? `turn ${fields.turn}` : ''
        case 'completed':
            return typeof fields.turns === 'number' ? `${fields.turns} turn${fields.turns === 1 ? '' : 's'}` : ''
        case 'failed':
            return typeof fields.error === 'string' ? fields.error : ''
        default:
            return compactJson(fields, 80)
    }
}

function compactJson(obj: Record<string, unknown>, max: number): string {
    const parts: string[] = []
    for (const [k, v] of Object.entries(obj)) {
        const valueStr = typeof v === 'string' ? v : JSON.stringify(v)
        parts.push(`${k}=${valueStr}`)
    }
    const joined = parts.join(' ')
    return joined.length > max ? joined.slice(0, max - 1) + '…' : joined
}

function short(id: string): string {
    return id.split('-').at(-1)?.slice(0, 8) ?? id.slice(0, 8)
}

function kindToneFor(kind: string): { badgeClass: string } {
    switch (kind) {
        case 'chat':
            return { badgeClass: 'bg-info/15 text-info-foreground' }
        case 'tool':
            return { badgeClass: 'bg-warning/15 text-warning-foreground' }
        case 'event':
            return { badgeClass: 'bg-success/15 text-success-foreground' }
        case 'error':
            return { badgeClass: 'bg-destructive/15 text-destructive' }
        case 'meta':
        default:
            return { badgeClass: 'bg-muted text-muted-foreground' }
    }
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
