'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback } from 'react'

import type { ChatSession } from '@posthog/agent-chat'
import type { LogEntry } from '@posthog/agent-chat/fixtures'

import { useAgent } from '@/components/agent-context'
import { useSetDockPage } from '@/components/dock-context'
import { useSessionTeamId } from '@/components/session-context'
import { SessionsList } from '@/components/SessionsList'
import { getSession, listLogsForSession, listSessionsForAgent } from '@/lib/apiClient'
import { changeKey } from '@/lib/changeFeed'
import { useResource } from '@/lib/useResource'
import { SessionDetail } from '@/screens/SessionDetail'

export function SessionsSegment(): React.ReactElement {
    const agent = useAgent()
    const teamId = useSessionTeamId()!
    const router = useRouter()
    const searchParams = useSearchParams()
    const selectedSessionId = searchParams?.get('session') ?? null

    // Dock context flips to "viewing a specific session" when one is
    // selected so the concierge greetings + starter prompts reflect it.
    useSetDockPage(
        selectedSessionId
            ? {
                  kind: 'agent-session',
                  agent: { id: agent.id, name: agent.name, slug: agent.slug },
                  sessionId: selectedSessionId,
              }
            : { kind: 'agent-sessions', agent: { id: agent.id, name: agent.name, slug: agent.slug } }
    )

    const sessions = useResource(
        () =>
            listSessionsForAgent(teamId, agent.slug, { id: agent.id, name: agent.name, slug: agent.slug }).catch(
                () => [] as ChatSession[]
            ),
        [teamId, agent.slug, agent.id],
        { key: changeKey('agent_session', teamId) }
    )

    const selectedSession = useResource(
        () =>
            selectedSessionId
                ? getSession(teamId, agent.slug, selectedSessionId, {
                      id: agent.id,
                      name: agent.name,
                      slug: agent.slug,
                  }).catch(() => null)
                : Promise.resolve(null),
        [teamId, agent.slug, selectedSessionId, agent.id],
        // Item key — refetch precisely when this open session transitions.
        { key: changeKey('agent_session', teamId, selectedSessionId ?? undefined) }
    )

    const selectedLogs = useResource(
        () =>
            selectedSessionId
                ? listLogsForSession(teamId, agent.slug, selectedSessionId).catch(() => [] as LogEntry[])
                : Promise.resolve([] as LogEntry[]),
        [teamId, agent.slug, selectedSessionId],
        { key: changeKey('agent_session', teamId, selectedSessionId ?? undefined) }
    )

    const select = useCallback(
        (id: string | null) => {
            const params = new URLSearchParams(searchParams?.toString() ?? '')
            if (id) {
                params.set('session', id)
            } else {
                params.delete('session')
            }
            const qs = params.toString()
            router.push(`/agents/${agent.slug}/sessions${qs ? `?${qs}` : ''}`, { scroll: false })
        },
        [agent.slug, router, searchParams]
    )

    const list = sessions.data ?? []

    // No selection → list takes the whole tab (centered + capped) so the
    // common "browse" path keeps the familiar full-width feel.
    if (!selectedSessionId) {
        return (
            <div className="mx-auto h-full w-full max-w-5xl overflow-y-auto px-6 pb-6 pt-4">
                <SessionsList sessions={list} selectedSessionId={null} onOpenSession={(id) => select(id)} />
            </div>
        )
    }

    return (
        <div className="grid h-full grid-cols-[minmax(280px,360px)_minmax(0,1fr)] divide-x divide-border">
            <aside className="flex min-h-0 flex-col overflow-hidden">
                <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
                    <SessionsList
                        sessions={list}
                        selectedSessionId={selectedSessionId}
                        onOpenSession={(id) => select(id)}
                    />
                </div>
            </aside>
            <main className="min-h-0 overflow-hidden">
                {selectedSession.data ? (
                    <SessionDetail
                        session={selectedSession.data}
                        logs={selectedLogs.data ?? []}
                        onClose={() => select(null)}
                    />
                ) : selectedSession.loading ? (
                    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                        Loading session…
                    </div>
                ) : (
                    <div className="flex h-full items-center justify-center px-4 text-center text-sm text-muted-foreground">
                        Couldn't load that session.
                    </div>
                )}
            </main>
        </div>
    )
}
