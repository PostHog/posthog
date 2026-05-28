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

    return (
        <AgentDetail
            agent={agent}
            revisions={revisions}
            bundle={bundle}
            stats={stats}
            sessions={sessions}
            onTryAgent={() => enterPlayground(agentRef)}
            onBackToList={() => router.push('/')}
            onOpenSession={(sessionId) => {
                // v0 placeholder — /sessions/<id> detail route lands in v1.
                // eslint-disable-next-line no-console
                console.info('[stub] session detail route lands in v1', sessionId)
            }}
        />
    )
}
