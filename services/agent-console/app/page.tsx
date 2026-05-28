/**
 * `/` — agents list landing page.
 *
 * v0: fetches everything from the mock REST stub. The page component
 * (`<AgentsList />`) doesn't change shape between v0 and v0.1 — only
 * the data source.
 *
 * RSC-friendly: this is a server component that fetches at request
 * time; the inner `<AgentsListClient />` is the interactive shell.
 */

import { countLiveSessionsForAgent, getFleetStats, listAgents, listLiveSessions } from '@/lib/mockApi'

import { AgentsListClient } from './agents-list-client'

export default async function HomePage(): Promise<React.ReactElement> {
    const [agents, fleetStats, liveSessions] = await Promise.all([
        listAgents({ latencyMs: 0 }),
        getFleetStats({ latencyMs: 0 }),
        listLiveSessions({ latencyMs: 0 }),
    ])

    // v0: simple sequential counts. v0.1: a single rollup endpoint returns
    // this map alongside fleet stats so we don't N+1 here.
    const liveCountByAgentEntries = await Promise.all(
        agents.map(async (a) => [a.id, await countLiveSessionsForAgent(a.id)] as const)
    )
    const liveCountByAgent = Object.fromEntries(liveCountByAgentEntries)

    return (
        <AgentsListClient
            agents={agents}
            fleetStats={fleetStats}
            liveSessions={liveSessions}
            liveCountByAgent={liveCountByAgent}
        />
    )
}
