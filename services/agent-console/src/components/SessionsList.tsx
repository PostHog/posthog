/**
 * Sessions tab — per-agent session history.
 *
 * Full-width list with filter chips above. Each row shows enough to
 * triage at a glance: state, trigger principal, task line, started/ended,
 * cost, plus an arrow to open the session detail (route lands in v1).
 *
 * Built to also serve as the body of a future cross-agent `/sessions`
 * page — at that point we'll add an `agent` column and the same
 * component handles both views.
 */

import { ChevronRightIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { ChatSession } from '@posthog/agent-chat'

import { FilterChips } from './FilterChips'

const FILTERS = ['all', 'live', 'completed', 'failed'] as const
type Filter = (typeof FILTERS)[number]

export interface SessionsListProps {
    sessions: ChatSession[]
    onOpenSession?: (sessionId: string) => void
}

const LIVE_STATES = new Set(['idle', 'streaming', 'awaiting_approval', 'awaiting_client_tool', 'disconnected'])
const FAILED_STATES = new Set(['failed', 'error', 'cancelled'])

export function SessionsList({ sessions, onOpenSession }: SessionsListProps): React.ReactElement {
    const [filter, setFilter] = useState<Filter>('all')

    const filtered = useMemo(() => {
        switch (filter) {
            case 'live':
                return sessions.filter((s) => LIVE_STATES.has(s.state))
            case 'completed':
                return sessions.filter((s) => s.state === 'completed')
            case 'failed':
                return sessions.filter((s) => FAILED_STATES.has(s.state))
            case 'all':
            default:
                return sessions
        }
    }, [sessions, filter])

    if (sessions.length === 0) {
        return (
            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
                No sessions yet.
            </div>
        )
    }

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between">
                <FilterChips
                    options={FILTERS}
                    value={filter}
                    onChange={setFilter}
                    labels={{ all: 'All', live: 'Live', completed: 'Completed', failed: 'Failed' }}
                />
                <span className="text-[0.6875rem] text-muted-foreground">
                    {filtered.length} of {sessions.length}
                </span>
            </div>

            {filtered.length === 0 ? (
                <div className="rounded-md border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                    No sessions match this filter.
                </div>
            ) : (
                <ul className="divide-y divide-border rounded-md border border-border bg-background">
                    {filtered.map((s) => (
                        <li key={s.id}>
                            <SessionRow session={s} onClick={() => onOpenSession?.(s.id)} />
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}

function SessionRow({ session, onClick }: { session: ChatSession; onClick?: () => void }): React.ReactElement {
    const tone = stateTone(session.state)
    // Prefer the user's task; the list endpoint only returns a preview
    // (last assistant text), so fall back to that when there's no
    // hydrated user turn.
    const taskLine = firstUserText(session) ?? firstAssistantText(session) ?? '—'
    const duration = durationLabel(session)
    return (
        <button
            type="button"
            onClick={onClick}
            className="group flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
        >
            <span className={`mt-1.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${tone.dotClass}`} aria-hidden />
            <div className="min-w-0 flex-1">
                <p className="line-clamp-1 text-sm">{taskLine}</p>
                <div className="mt-0.5 flex items-center gap-2 text-[0.6875rem] text-muted-foreground">
                    <span>{tone.label}</span>
                    <span>·</span>
                    <span className="truncate">{session.principal.displayName}</span>
                    {session.error ? (
                        <>
                            <span>·</span>
                            <span className="truncate text-destructive">{session.error}</span>
                        </>
                    ) : null}
                </div>
            </div>
            <div className="flex shrink-0 items-center gap-4 text-[0.6875rem] text-muted-foreground">
                <span className="font-mono tabular-nums">${session.usage.costUsd.toFixed(3)}</span>
                <span className="hidden font-mono tabular-nums sm:inline">{duration}</span>
                <span className="hidden md:inline">{startedLabel(session)}</span>
                <ChevronRightIcon className="h-3.5 w-3.5 text-muted-foreground/60 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
            </div>
        </button>
    )
}

function stateTone(state: ChatSession['state']): { dotClass: string; label: string } {
    switch (state) {
        case 'streaming':
            return { dotClass: 'bg-info animate-pulse', label: 'streaming' }
        case 'awaiting_approval':
            return { dotClass: 'bg-warning', label: 'awaiting approval' }
        case 'awaiting_client_tool':
            return { dotClass: 'bg-info', label: 'awaiting client' }
        case 'completed':
            return { dotClass: 'bg-success', label: 'completed' }
        case 'failed':
        case 'error':
            return { dotClass: 'bg-destructive', label: state }
        case 'cancelled':
            return { dotClass: 'bg-muted-foreground/60', label: 'cancelled' }
        case 'disconnected':
            return { dotClass: 'bg-muted-foreground/60', label: 'disconnected' }
        case 'idle':
        default:
            return { dotClass: 'bg-success', label: 'idle' }
    }
}

function firstUserText(session: ChatSession): string | null {
    for (const turn of session.turns) {
        if (turn.kind === 'user') {
            return turn.text
        }
    }
    return null
}

function firstAssistantText(session: ChatSession): string | null {
    for (const turn of session.turns) {
        if (turn.kind === 'assistant') {
            for (const p of turn.parts) {
                if (p.kind === 'text') {
                    return p.text
                }
            }
        }
    }
    return null
}

function durationLabel(session: ChatSession): string {
    if (!session.started_at) {
        return '—'
    }
    const start = new Date(session.started_at).getTime()
    const end = session.ended_at ? new Date(session.ended_at).getTime() : Date.now()
    const ms = Math.max(0, end - start)
    return formatDuration(ms)
}

function formatDuration(ms: number): string {
    const s = Math.floor(ms / 1000)
    if (s < 60) {
        return `${s}s`
    }
    const m = Math.floor(s / 60)
    const rem = s % 60
    return rem === 0 ? `${m}m` : `${m}m ${rem}s`
}

function startedLabel(session: ChatSession): string {
    if (!session.started_at) {
        return '—'
    }
    const ts = new Date(session.started_at).getTime()
    const diff = Math.max(0, Date.now() - ts)
    const minute = 60 * 1000
    const hour = 60 * minute
    const day = 24 * hour
    if (diff < minute) {
        return 'just now'
    }
    if (diff < hour) {
        return `${Math.floor(diff / minute)}m ago`
    }
    if (diff < day) {
        return `${Math.floor(diff / hour)}h ago`
    }
    return `${Math.floor(diff / day)}d ago`
}
