/**
 * `<LiveNowPanel />` — what's running across the fleet right now.
 *
 * Each row shows the agent the session is against, who/what triggered
 * it, a short task line, and the time. State is conveyed by the
 * leading dot (streaming · awaiting approval · awaiting client).
 *
 * v0: takes pre-fetched sessions as a prop. v0.1: will swap to
 * `EventSource` for live updates against `/listen`.
 *
 * Designed to be reusable: also the body of a future cross-agent
 * `/sessions` page once we have one.
 */

import { ChevronRightIcon } from 'lucide-react'
import { useMemo } from 'react'

import type { ChatSession, SessionState } from '@posthog/agent-chat'

export interface LiveNowPanelProps {
    sessions: ChatSession[]
    /** Cap the number of rows rendered. Default 6. */
    limit?: number
    onOpenSession?: (sessionId: string) => void
    onOpenAgent?: (slug: string) => void
    /** Optional "view all" affordance — wired to a future cross-agent sessions page. */
    onViewAll?: () => void
}

export function LiveNowPanel({
    sessions,
    limit = 6,
    onOpenSession,
    onOpenAgent,
    onViewAll,
}: LiveNowPanelProps): React.ReactElement {
    const sorted = useMemo(() => {
        return [...sessions].sort((a, b) => timestamp(b) - timestamp(a)).slice(0, limit)
    }, [sessions, limit])

    return (
        <div className="flex h-full flex-col">
            {/* Header sits outside the bordered card so it aligns with
                the filter-chips toolbar on the left column. The fixed
                h-8 matches AgentsList's toolbar row so both columns'
                bordered cards start at the same baseline. */}
            <div className="mb-3 flex h-8 items-center justify-between px-1">
                <div className="flex items-center gap-1.5">
                    <span className="inline-flex h-1.5 w-1.5 animate-pulse rounded-full bg-warning" aria-hidden />
                    <span className="text-xs font-medium">Live now</span>
                    <span className="text-xs text-muted-foreground">· {sessions.length}</span>
                </div>
                {onViewAll ? (
                    <button
                        type="button"
                        onClick={onViewAll}
                        className="cursor-pointer text-[0.6875rem] text-muted-foreground transition-colors hover:text-foreground"
                    >
                        View all
                    </button>
                ) : null}
            </div>

            <div className="flex flex-1 flex-col overflow-hidden rounded-md border border-border bg-card">
                {sorted.length === 0 ? (
                    <div className="flex flex-1 items-center justify-center px-4 py-8 text-center text-xs text-muted-foreground">
                        Nothing running.
                    </div>
                ) : (
                    <ul className="flex-1 divide-y divide-border overflow-y-auto">
                        {sorted.map((s) => (
                            <li key={s.id}>
                                <SessionRow session={s} onOpenSession={onOpenSession} onOpenAgent={onOpenAgent} />
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </div>
    )
}

function SessionRow({
    session,
    onOpenSession,
    onOpenAgent,
}: {
    session: ChatSession
    onOpenSession?: (sessionId: string) => void
    onOpenAgent?: (slug: string) => void
}): React.ReactElement {
    const tone = stateTone(session.state)
    const taskLine = lastUserText(session) ?? '—'
    const handleClick = (): void => {
        if (onOpenSession) {
            onOpenSession(session.id)
        } else if (onOpenAgent) {
            onOpenAgent(session.application.slug)
        }
    }
    return (
        <button
            type="button"
            onClick={handleClick}
            className="group flex w-full cursor-pointer items-start gap-2 px-3 py-2.5 text-left transition-colors hover:bg-accent/40 focus-visible:bg-accent/40 focus-visible:outline-none"
        >
            <span className={`mt-1.5 inline-flex h-1.5 w-1.5 shrink-0 rounded-full ${tone.dotClass}`} aria-hidden />
            <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5 text-xs">
                    <span className="truncate font-medium">{session.application.name}</span>
                    <span className="text-muted-foreground">·</span>
                    <span className="truncate text-muted-foreground">{tone.label}</span>
                </div>
                <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{taskLine}</p>
                <div className="mt-1 flex items-center gap-2 text-[0.6875rem] text-muted-foreground/80">
                    <span className="truncate">{session.principal.displayName}</span>
                    <span>·</span>
                    <span>{formatRelative(timestamp(session))}</span>
                </div>
            </div>
            <ChevronRightIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground/60 transition-all group-hover:translate-x-0.5 group-hover:text-foreground" />
        </button>
    )
}

function stateTone(state: SessionState): { dotClass: string; label: string } {
    switch (state) {
        case 'streaming':
            return { dotClass: 'bg-info animate-pulse', label: 'streaming' }
        case 'awaiting_user_input':
            return { dotClass: 'bg-warning', label: 'awaiting user input' }
        case 'awaiting_client_tool':
            return { dotClass: 'bg-info', label: 'awaiting client' }
        case 'error':
            return { dotClass: 'bg-destructive', label: 'errored' }
        case 'disconnected':
            return { dotClass: 'bg-muted-foreground/60', label: 'disconnected' }
        case 'idle':
        default:
            return { dotClass: 'bg-success', label: 'idle' }
    }
}

function lastUserText(session: ChatSession): string | null {
    for (let i = session.turns.length - 1; i >= 0; i--) {
        const t = session.turns[i]
        if (t.kind === 'user') {
            return t.text
        }
    }
    // Fall back to the first turn (user or assistant text part).
    const first = session.turns[0]
    if (!first) {
        return null
    }
    if (first.kind === 'user') {
        return first.text
    }
    const textPart = first.parts.find((p): p is { kind: 'text'; text: string } => p.kind === 'text')
    return textPart?.text ?? null
}

function timestamp(session: ChatSession): number {
    if (session.started_at) {
        return new Date(session.started_at).getTime()
    }
    if (session.turns[0]) {
        return new Date(session.turns[0].timestamp).getTime()
    }
    return 0
}

function formatRelative(ms: number): string {
    if (!ms) {
        return '—'
    }
    const diff = Math.max(0, Date.now() - ms)
    const minute = 60 * 1000
    const hour = 60 * minute
    if (diff < minute) {
        return 'just now'
    }
    if (diff < hour) {
        return `${Math.floor(diff / minute)}m ago`
    }
    return `${Math.floor(diff / hour)}h ago`
}
