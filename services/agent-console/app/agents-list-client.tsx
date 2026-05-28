'use client'

import { useRouter } from 'next/navigation'

import type { ChatSession } from '@posthog/agent-chat'
import type { AgentApplicationFixture, FleetStats } from '@posthog/agent-chat/fixtures'

import { useSetDockPage } from '@/components/dock-context'
import { AgentsList } from '@/pages/AgentsList'

export function AgentsListClient({
    agents,
    fleetStats,
    liveSessions,
    liveCountByAgent,
}: {
    agents: AgentApplicationFixture[]
    fleetStats: FleetStats
    liveSessions: ChatSession[]
    liveCountByAgent: Record<string, number>
}): React.ReactElement {
    const router = useRouter()
    useSetDockPage({ kind: 'agent-list' })

    return (
        <AgentsList
            agents={agents}
            fleetStats={fleetStats}
            liveSessions={liveSessions}
            liveCountByAgent={liveCountByAgent}
            onOpenAgent={(slug) => router.push(`/agents/${slug}`)}
            onOpenSession={(sessionId) => {
                // v0 placeholder — cross-agent /sessions/<id> route lands in v1.
                // eslint-disable-next-line no-console
                console.info('[stub] session detail route lands in v1', sessionId)
            }}
            onCreateAgent={() => {
                // eslint-disable-next-line no-console
                console.info('[stub] Create-agent flow lives in the concierge chat dock (v0.2).')
            }}
            onViewAllSessions={() => {
                // eslint-disable-next-line no-console
                console.info('[stub] /sessions cross-agent page lands in v1.')
            }}
        />
    )
}
