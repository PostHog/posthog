'use client'

import { useRouter } from 'next/navigation'

import type { ChatSession } from '@posthog/agent-chat'
import type {
    AgentApplicationFixture,
    AgentRevisionFixture,
    AgentStats,
    BundleFile,
} from '@posthog/agent-chat/fixtures'

import { useDockStore, useSetDockPage } from '@/components/dock-context'
import { useMutatingBundle } from '@/components/use-mutating-bundle'
import { AgentDetail } from '@/pages/AgentDetail'

export function AgentDetailClient({
    agent,
    revisions,
    bundle,
    stats,
    sessions,
}: {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    bundle: BundleFile[]
    stats: AgentStats
    sessions: ChatSession[]
}): React.ReactElement {
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }
    useSetDockPage({ kind: 'agent', agent: agentRef })

    const { enterPlayground } = useDockStore()
    const router = useRouter()

    // The server-rendered bundle is the starting point; subsequent
    // mutations driven by the runner re-read from mockApi's overlay.
    const { bundle: liveBundle } = useMutatingBundle(agent.id, bundle)

    return (
        <AgentDetail
            agent={agent}
            revisions={revisions}
            bundle={liveBundle}
            stats={stats}
            sessions={sessions}
            onTryAgent={() => enterPlayground(agentRef)}
            onBackToList={() => router.push('/')}
            onOpenSession={(sessionId) => router.push(`/agents/${agent.slug}/sessions/${sessionId}`)}
        />
    )
}
