'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useState } from 'react'

import type { LogEntry } from '@posthog/agent-chat/fixtures'

import { useAgent } from '@/components/agent-context'
import { useSetDockPage } from '@/components/dock-context'
import { usePosthogBaseUrl, useSessionTeamId } from '@/components/session-context'
import { SessionsList } from '@/components/SessionsList'
import { getSession, listLogsForSession, listSessionsForAgent } from '@/lib/apiClient'
import { aiObservabilityTraceUrl } from '@/lib/posthogLinks'
import { useResource } from '@/lib/useResource'
import { SessionDetail } from '@/screens/SessionDetail'

const PAGE_SIZE = 20

export function SessionsSegment(): React.ReactElement {
    const agent = useAgent()
    const teamId = useSessionTeamId()!
    const posthogBaseUrl = usePosthogBaseUrl()
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

    // Sessions and their logs change while an agent is running, so these
    // reads poll on a short interval (visibility-aware — quiet in a
    // background tab, catches up on focus).
    const POLL_MS = 10_000

    // Pagination: start with PAGE_SIZE rows, grow the window on "Load more".
    // We re-fetch the whole window instead of merging pages so the same
    // poll machinery keeps streaming rows fresh.
    const [limit, setLimit] = useState(PAGE_SIZE)

    const sessions = useResource(
        () =>
            listSessionsForAgent(
                teamId,
                agent.slug,
                { id: agent.id, name: agent.name, slug: agent.slug },
                { limit }
            ).catch(() => ({ sessions: [], count: 0 })),
        [teamId, agent.slug, agent.id, limit],
        { pollMs: POLL_MS }
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
        { pollMs: POLL_MS }
    )

    const selectedLogs = useResource(
        () =>
            selectedSessionId
                ? listLogsForSession(teamId, agent.slug, selectedSessionId).catch(() => [] as LogEntry[])
                : Promise.resolve([] as LogEntry[]),
        [teamId, agent.slug, selectedSessionId],
        { pollMs: POLL_MS }
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

    const list = sessions.data?.sessions ?? []
    const totalCount = sessions.data?.count ?? list.length
    const hasMore = list.length < totalCount
    const loadMore = useCallback(() => setLimit((l) => l + PAGE_SIZE), [])

    // No selection → list takes the whole tab (centered + capped) so the
    // common "browse" path keeps the familiar full-width feel. SessionsList
    // owns its own scroll so the filter chips stay pinned at the top.
    if (!selectedSessionId) {
        return (
            <div className="mx-auto flex h-full w-full max-w-5xl flex-col px-6 pb-6 pt-4">
                <SessionsList
                    sessions={list}
                    selectedSessionId={null}
                    onOpenSession={(id) => select(id)}
                    totalCount={totalCount}
                    hasMore={hasMore}
                    onLoadMore={loadMore}
                    loadingMore={sessions.loading && list.length > 0 && list.length < limit}
                />
            </div>
        )
    }

    return (
        <div className="grid h-full grid-cols-[minmax(280px,360px)_minmax(0,1fr)] divide-x divide-border">
            <aside className="flex min-h-0 flex-col overflow-hidden">
                <div className="flex min-h-0 flex-1 flex-col px-3 py-3">
                    <SessionsList
                        sessions={list}
                        selectedSessionId={selectedSessionId}
                        onOpenSession={(id) => select(id)}
                        totalCount={totalCount}
                        hasMore={hasMore}
                        onLoadMore={loadMore}
                        loadingMore={sessions.loading && list.length > 0 && list.length < limit}
                    />
                </div>
            </aside>
            <main className="min-h-0 overflow-hidden">
                {selectedSession.data ? (
                    <SessionDetail
                        session={selectedSession.data}
                        logs={selectedLogs.data ?? []}
                        onClose={() => select(null)}
                        aiObservabilityTraceUrl={
                            posthogBaseUrl && selectedSessionId
                                ? aiObservabilityTraceUrl(posthogBaseUrl, teamId, selectedSessionId)
                                : undefined
                        }
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
