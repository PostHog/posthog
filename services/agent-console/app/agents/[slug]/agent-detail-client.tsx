'use client'

import { notFound, useRouter } from 'next/navigation'

import { useSetDockPage, useDockStore } from '@/components/dock-context'
import { useMutatingBundle } from '@/components/use-mutating-bundle'
import { useMutatingRevisions } from '@/components/use-mutating-revisions'
import { ApiError, getAgent, getAgentStats, listSessionsForAgent } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { AgentDetail } from '@/pages/AgentDetail'

export function AgentDetailClient({ slug }: { slug: string }): React.ReactElement {
    const router = useRouter()

    const agent = useResource(() => getAgent(slug), [slug])

    if (agent.error instanceof ApiError && agent.error.status === 404) {
        notFound()
    }
    if (agent.error) {
        return <div className="px-6 py-6 text-sm text-destructive">Failed to load: {agent.error.message}</div>
    }
    if (!agent.data) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Loading…</div>
    }
    return (
        <AgentDetailInner
            slug={slug}
            agent={agent.data}
            onBackToList={() => router.push('/')}
            onOpenSession={(sessionId) => router.push(`/agents/${slug}/sessions/${sessionId}`)}
        />
    )
}

function AgentDetailInner({
    slug,
    agent,
    onBackToList,
    onOpenSession,
}: {
    slug: string
    agent: Awaited<ReturnType<typeof getAgent>>
    onBackToList: () => void
    onOpenSession: (sessionId: string) => void
}): React.ReactElement {
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }
    useSetDockPage({ kind: 'agent', agent: agentRef })

    const { enterPlayground } = useDockStore()

    const stats = useResource(() => getAgentStats(slug), [slug])
    const sessions = useResource(() => listSessionsForAgent(slug), [slug])
    const { revisions, loading: revisionsLoading } = useMutatingRevisions(slug, agent.id)
    const { bundle, loading: bundleLoading } = useMutatingBundle(slug, agent.id)

    if (stats.error ?? sessions.error) {
        const message = (stats.error ?? sessions.error)?.message ?? 'Unknown error'
        return <div className="px-6 py-6 text-sm text-destructive">Failed to load: {message}</div>
    }
    if (stats.loading || sessions.loading || revisionsLoading || bundleLoading || !stats.data || !sessions.data) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Loading…</div>
    }

    return (
        <AgentDetail
            agent={agent}
            revisions={revisions}
            bundle={bundle}
            stats={stats.data}
            sessions={sessions.data}
            onTryAgent={() => enterPlayground(agentRef)}
            onBackToList={onBackToList}
            onOpenSession={onOpenSession}
        />
    )
}
