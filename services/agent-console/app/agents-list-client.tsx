'use client'

import { useRouter } from 'next/navigation'

import { useSetDockPage } from '@/components/dock-context'
import { useSessionTeamId } from '@/components/session-context'
import { getFleetStats, listAgents, listLiveSessions } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { AgentsList } from '@/pages/AgentsList'

export function AgentsListClient(): React.ReactElement {
    const router = useRouter()
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!
    useSetDockPage({ kind: 'agent-list' })

    const agents = useResource(() => listAgents(teamId), [teamId])
    const fleet = useResource(() => getFleetStats(teamId), [teamId])
    const live = useResource(() => listLiveSessions(teamId), [teamId])

    const loading = agents.loading || fleet.loading || live.loading
    const error = agents.error ?? fleet.error ?? live.error

    if (error) {
        return <div className="px-6 py-6 text-sm text-destructive">Failed to load: {error.message}</div>
    }
    if (loading || !agents.data || !fleet.data || !live.data) {
        return <div className="px-6 py-6 text-sm text-muted-foreground">Loading…</div>
    }

    const liveSessions = live.data
    // v0: count live sessions per agent by grouping the fleet list
    // client-side. v0.1+ surfaces this as a fleet/rollup field.
    const liveCountByAgent = liveSessions.reduce<Record<string, number>>((acc, s) => {
        acc[s.application.id] = (acc[s.application.id] ?? 0) + 1
        return acc
    }, {})

    return (
        <AgentsList
            agents={agents.data}
            fleetStats={fleet.data}
            liveSessions={liveSessions}
            liveCountByAgent={liveCountByAgent}
            onOpenAgent={(slug) => router.push(`/agents/${slug}`)}
            onOpenSession={(sessionId) => {
                const session = liveSessions.find((s) => s.id === sessionId)
                if (session) {
                    router.push(`/agents/${session.application.slug}/sessions/${sessionId}`)
                }
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
