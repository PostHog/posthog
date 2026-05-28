/**
 * Session detail — playback on the left (what the conversation looked
 * like in its native habitat) + log entries on the right (what the
 * runtime was doing). Cross-link via callId so clicking a tool call
 * on either side highlights the matching row on the other.
 */

'use client'

import { ChevronRightIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type { AgentApplicationFixture, LogEntry } from '@posthog/agent-chat/fixtures'

import { SessionLogs } from '@/components/SessionLogs'
import { SessionPlayback } from '@/components/SessionPlayback'
import { StatStrip, type StatTile } from '@/components/StatStrip'

export interface SessionDetailProps {
    agent: AgentApplicationFixture
    session: ChatSession
    logs: LogEntry[]
    onBackToAgent?: () => void
    onBackToList?: () => void
}

export function SessionDetail({
    agent,
    session,
    logs,
    onBackToAgent,
    onBackToList,
}: SessionDetailProps): React.ReactElement {
    const [highlightedCallId, setHighlightedCallId] = useState<string | null>(null)
    const playbackRef = useRef<HTMLDivElement>(null)
    const logsRef = useRef<HTMLDivElement>(null)

    // When a callId is selected from one pane, scroll the other to match.
    useEffect(() => {
        if (!highlightedCallId) {
            return
        }
        // Scroll both panes so the matching row/card is visible.
        const playbackTarget = playbackRef.current?.querySelector(`[data-call-id="${highlightedCallId}"]`)
        playbackTarget?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        const logsTarget = logsRef.current?.querySelector(`[data-call-id="${highlightedCallId}"]`)
        logsTarget?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }, [highlightedCallId])

    const tiles = buildTiles(session, logs)

    return (
        <div className="flex h-full flex-col px-6 py-6">
            <Breadcrumb
                agentName={agent.name}
                sessionShort={shortId(session.id)}
                onBackToList={onBackToList}
                onBackToAgent={onBackToAgent}
            />

            <header className="mt-3">
                <h1 className="text-xl font-medium tracking-tight">{summary(session)}</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                    {agent.name} · <code className="text-[0.6875rem]">{shortId(session.id)}</code> ·{' '}
                    {session.principal.displayName}
                </p>
            </header>

            <StatStrip tiles={tiles} className="mt-4" />

            <div className="mt-4 grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                <div ref={playbackRef} className="min-w-0">
                    <SessionPlayback
                        session={session}
                        highlightedCallId={highlightedCallId}
                        onSelectCallId={setHighlightedCallId}
                    />
                </div>
                <div ref={logsRef} className="min-w-0">
                    <SessionLogs
                        logs={logs}
                        sessionStartedAt={session.started_at}
                        highlightedCallId={highlightedCallId}
                        onSelectCallId={setHighlightedCallId}
                    />
                </div>
            </div>
        </div>
    )
}

/* ── Helpers ─────────────────────────────────────────────────────── */

function Breadcrumb({
    agentName,
    sessionShort,
    onBackToList,
    onBackToAgent,
}: {
    agentName: string
    sessionShort: string
    onBackToList?: () => void
    onBackToAgent?: () => void
}): React.ReactElement {
    return (
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
            {onBackToList ? (
                <button type="button" onClick={onBackToList} className="cursor-pointer hover:text-foreground">
                    Agents
                </button>
            ) : (
                <span>Agents</span>
            )}
            <ChevronRightIcon className="h-3 w-3" />
            {onBackToAgent ? (
                <button type="button" onClick={onBackToAgent} className="cursor-pointer hover:text-foreground">
                    {agentName}
                </button>
            ) : (
                <span>{agentName}</span>
            )}
            <ChevronRightIcon className="h-3 w-3" />
            <span className="text-foreground">{sessionShort}</span>
        </div>
    )
}

function summary(session: ChatSession): string {
    for (const turn of session.turns) {
        if (turn.kind === 'user') {
            return turn.text
        }
    }
    return `Session ${shortId(session.id)}`
}

function buildTiles(session: ChatSession, logs: LogEntry[]): StatTile[] {
    const toolCalls = session.turns.reduce((acc, turn) => {
        if (turn.kind !== 'assistant') {
            return acc
        }
        return acc + turn.parts.filter((p) => p.kind === 'tool_call').length
    }, 0)
    const durationMs =
        session.started_at && session.ended_at
            ? new Date(session.ended_at).getTime() - new Date(session.started_at).getTime()
            : null

    const errorCount = logs.filter((e) => e.level === 'error' || e.level === 'fatal').length

    return [
        { label: 'State', value: session.state },
        { label: 'Tool calls', value: toolCalls },
        { label: 'Cost', value: `$${session.usage.costUsd.toFixed(3)}` },
        {
            label: 'Duration',
            value: durationMs !== null ? formatDuration(durationMs) : 'in flight',
        },
        ...(errorCount > 0
            ? [{ label: 'Errors', value: errorCount, tone: 'attention' as const, hint: 'in logs' }]
            : []),
    ]
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

function shortId(id: string): string {
    return id.split('-').at(-1)?.slice(0, 8) ?? id.slice(0, 8)
}
