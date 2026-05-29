'use client'

import { notFound, useRouter, useSearchParams } from 'next/navigation'

import { useSetDockPage, useDockStore } from '@/components/dock-context'
import { ApiError, getAgent, getAgentStats, listRevisions, listSessionsForAgent } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { AgentDetail, parseUrlState, type AgentDetailUrlState } from '@/pages/AgentDetail'

export function AgentDetailClient({ slug }: { slug: string }): React.ReactElement {
    const router = useRouter()
    const searchParams = useSearchParams()

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

    const urlState = parseUrlState(new URLSearchParams(searchParams?.toString() ?? ''), agent.data.live_revision)

    const onChangeUrlState = (next: Partial<AgentDetailUrlState>): void => {
        const merged: AgentDetailUrlState = { ...urlState, ...next }
        const params = new URLSearchParams()
        if (merged.tab !== 'overview') {
            params.set('tab', merged.tab)
        }
        if (merged.revisionId && merged.revisionId !== agent.data!.live_revision) {
            params.set('revision', merged.revisionId)
        }
        if (merged.section) {
            params.set('section', merged.section)
        }
        if (merged.filePath) {
            params.set('file', merged.filePath)
        }
        const qs = params.toString()
        router.push(`/agents/${slug}${qs ? `?${qs}` : ''}`)
    }

    return (
        <AgentDetailInner
            slug={slug}
            agent={agent.data}
            urlState={urlState}
            onChangeUrlState={onChangeUrlState}
            onBackToList={() => router.push('/')}
            onOpenSession={(sessionId) => router.push(`/agents/${slug}/sessions/${sessionId}`)}
        />
    )
}

function AgentDetailInner({
    slug,
    agent,
    urlState,
    onChangeUrlState,
    onBackToList,
    onOpenSession,
}: {
    slug: string
    agent: Awaited<ReturnType<typeof getAgent>>
    urlState: AgentDetailUrlState
    onChangeUrlState: (next: Partial<AgentDetailUrlState>) => void
    onBackToList: () => void
    onOpenSession: (sessionId: string) => void
}): React.ReactElement {
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }
    useSetDockPage({ kind: 'agent', agent: agentRef })

    const { enterPlayground } = useDockStore()

    const stats = useResource(() => getAgentStats(slug), [slug])
    const sessions = useResource(() => listSessionsForAgent(slug), [slug])
    const revisions = useResource(() => listRevisions(slug), [slug])

    if (stats.error ?? sessions.error ?? revisions.error) {
        const message = (stats.error ?? sessions.error ?? revisions.error)?.message ?? 'Unknown error'
        return <div className="px-6 py-6 text-sm text-destructive">Failed to load: {message}</div>
    }
    if (!stats.data || !sessions.data || !revisions.data) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Loading…</div>
    }

    return (
        <AgentDetail
            agent={agent}
            revisions={revisions.data}
            stats={stats.data}
            sessions={sessions.data}
            urlState={urlState}
            onChangeUrlState={onChangeUrlState}
            onTryAgent={() => enterPlayground(agentRef)}
            onBackToList={onBackToList}
            onOpenSession={onOpenSession}
        />
    )
}
