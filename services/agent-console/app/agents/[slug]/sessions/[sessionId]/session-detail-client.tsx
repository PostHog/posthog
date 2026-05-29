'use client'

import { notFound, useRouter } from 'next/navigation'

import { useSetDockPage } from '@/components/dock-context'
import { useSessionTeamId } from '@/components/session-context'
import { ApiError, getAgent, getSession, listLogsForSession } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { SessionDetail } from '@/pages/SessionDetail'

export function SessionDetailClient({ slug, sessionId }: { slug: string; sessionId: string }): React.ReactElement {
    const router = useRouter()
    const teamId = useSessionTeamId()

    const agent = useResource(() => (teamId == null ? pending() : getAgent(teamId, slug)), [teamId, slug])
    const session = useResource(
        () => (teamId == null ? pending() : getSession(teamId, slug, sessionId)),
        [teamId, slug, sessionId]
    )
    const logs = useResource(
        () => (teamId == null ? pending() : listLogsForSession(teamId, slug, sessionId)),
        [teamId, slug, sessionId]
    )

    if (teamId == null) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Resolving project…</div>
    }
    if (
        (agent.error instanceof ApiError && agent.error.status === 404) ||
        (session.error instanceof ApiError && session.error.status === 404)
    ) {
        notFound()
    }
    const error = agent.error ?? session.error ?? logs.error
    if (error) {
        return <div className="px-6 py-6 text-sm text-destructive">Failed to load: {error.message}</div>
    }
    if (!agent.data || !session.data || !logs.data) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Loading…</div>
    }

    return (
        <SessionDetailInner
            slug={slug}
            agent={agent.data}
            session={session.data}
            logs={logs.data}
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

function pending<T = never>(): Promise<T> {
    return new Promise<T>(() => undefined)
}
