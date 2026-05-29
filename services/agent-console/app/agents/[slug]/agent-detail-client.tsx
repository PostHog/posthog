'use client'

import { notFound, useRouter, useSearchParams } from 'next/navigation'

import type { ChatSession } from '@posthog/agent-chat'

import { useSetDockPage, useDockStore } from '@/components/dock-context'
import { useSessionTeamId } from '@/components/session-context'
import { ApiError, getAgent, getAgentStats, listRevisions, listSessionsForAgent } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { AgentDetail, parseUrlState, type AgentDetailUrlState } from '@/pages/AgentDetail'

export function AgentDetailClient({ slug }: { slug: string }): React.ReactElement {
    const router = useRouter()
    const searchParams = useSearchParams()
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!

    const agent = useResource(() => getAgent(teamId, slug), [teamId, slug])

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
            teamId={teamId}
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
    teamId,
    agent,
    urlState,
    onChangeUrlState,
    onBackToList,
    onOpenSession,
}: {
    slug: string
    teamId: number
    agent: Awaited<ReturnType<typeof getAgent>>
    urlState: AgentDetailUrlState
    onChangeUrlState: (next: Partial<AgentDetailUrlState>) => void
    onBackToList: () => void
    onOpenSession: (sessionId: string) => void
}): React.ReactElement {
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }
    useSetDockPage({ kind: 'agent', agent: agentRef })

    const { enterPlayground } = useDockStore()

    // Stats: Phase C endpoint, may 404. Treat any failure as "no stats yet".
    // Sessions: proxies the janitor — may 502 if it isn't running locally.
    //   Render with an empty list rather than failing the whole page.
    // Revisions + agent: must succeed.
    const stats = useResource(() => getAgentStats(teamId, slug).catch(() => null), [teamId, slug])
    const sessions = useResource(
        () => listSessionsForAgent(teamId, slug).catch(() => [] as ChatSession[]),
        [teamId, slug]
    )
    const revisions = useResource(() => listRevisions(teamId, slug), [teamId, slug])

    if (revisions.error) {
        return <div className="px-6 py-6 text-sm text-destructive">Failed to load: {revisions.error.message}</div>
    }
    if (stats.loading || sessions.loading || revisions.loading || !revisions.data) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Loading…</div>
    }

    const effectiveStats = stats.data ?? {
        liveCount: 0,
        sessions24hCount: 0,
        spend24hUsd: 0,
        lastActivityAt: undefined,
        failureRate24h: undefined,
    }
    const effectiveSessions = sessions.data ?? []

    return (
        <AgentDetail
            agent={agent}
            revisions={revisions.data}
            stats={effectiveStats}
            sessions={effectiveSessions}
            urlState={urlState}
            onChangeUrlState={onChangeUrlState}
            onTryAgent={() => enterPlayground(agentRef)}
            onBackToList={onBackToList}
            onOpenSession={onOpenSession}
        />
    )
}
