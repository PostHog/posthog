'use client'

import { notFound, useRouter } from 'next/navigation'

import type { LogEntry } from '@posthog/agent-chat/fixtures'

import { useSetDockPage } from '@/components/dock-context'
import { useSessionTeamId } from '@/components/session-context'
import { ApiError, getAgent, getSession, listLogsForSession } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { SessionDetail } from '@/pages/SessionDetail'

export function SessionDetailClient({ slug, sessionId }: { slug: string; sessionId: string }): React.ReactElement {
    const router = useRouter()
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!

    const agent = useResource(() => getAgent(teamId, slug), [teamId, slug])
    const session = useResource(() => getSession(teamId, slug, sessionId), [teamId, slug, sessionId])
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
    if (!agent.data || !session.data || logs.loading) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Loading…</div>
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
