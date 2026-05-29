'use client'

import { notFound, useRouter } from 'next/navigation'

import type { LogEntry } from '@posthog/agent-chat/fixtures'

import { useSetDockPage } from '@/components/dock-context'
import { SessionDetailSkeleton } from '@/components/PageSkeletons'
import { useSessionTeamId } from '@/components/session-context'
import { ApiError, getAgent, getSession, listLogsForSession } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { SessionDetail } from '@/pages/SessionDetail'

export function SessionDetailClient({ slug, sessionId }: { slug: string; sessionId: string }): React.ReactElement {
    const router = useRouter()
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!

    const agent = useResource(() => getAgent(teamId, slug), [teamId, slug])
    const session = useResource(
        () =>
            agent.data
                ? getSession(teamId, slug, sessionId, {
                      id: agent.data.id,
                      name: agent.data.name,
                      slug: agent.data.slug,
                  })
                : Promise.resolve(null),
        [teamId, slug, sessionId, agent.data?.id]
    )
    // Logs is Phase C (no Django endpoint yet). Tolerate any failure
    // and render an empty entries pane — the playback half still works.
    const logs = useResource(
        () => listLogsForSession(teamId, slug, sessionId).catch(() => [] as LogEntry[]),
        [teamId, slug, sessionId]
    )

    if (
        (agent.error instanceof ApiError && agent.error.status === 404) ||
        (session.error instanceof ApiError && session.error.status === 404)
    ) {
        notFound()
    }
    const error = agent.error ?? session.error
    if (error) {
        return <div className="px-6 py-6 text-sm text-destructive">Failed to load: {error.message}</div>
    }
    // Stale-while-revalidate: render with prior data while a refetch
    // (e.g. from bumpReload after promote) is in flight. logs is best-
    // effort — its data can be null on first paint, treat as empty.
    if (!agent.data || !session.data) {
        return <SessionDetailSkeleton />
    }

    return (
        <SessionDetailInner
            slug={slug}
            agent={agent.data}
            session={session.data}
            logs={logs.data ?? []}
            onBackToList={() => router.push('/')}
            onBackToAgent={() => router.push(`/agents/${slug}`)}
        />
    )
}

function SessionDetailInner({
    slug,
    agent,
    session,
    logs,
    onBackToList,
    onBackToAgent,
}: {
    slug: string
    agent: Awaited<ReturnType<typeof getAgent>>
    session: Awaited<ReturnType<typeof getSession>>
    logs: Awaited<ReturnType<typeof listLogsForSession>>
    onBackToList: () => void
    onBackToAgent: () => void
}): React.ReactElement {
    void slug
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }
    useSetDockPage({ kind: 'agent-session', agent: agentRef, sessionId: session.id })

    return (
        <SessionDetail
            agent={agent}
            session={session}
            logs={logs}
            onBackToList={onBackToList}
            onBackToAgent={onBackToAgent}
        />
    )
}
