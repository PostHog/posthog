'use client'

import { useSetDockConciergeAgent, useSetDockPage } from '@/components/dock-context'
import { useSessionTeamId, useSessionUser } from '@/components/session-context'
import { ApiError, getFleetStats, listAgents } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { Overview } from '@/screens/Overview'

/** Treat a 404 as "this endpoint isn't built yet" and return null. */
async function tolerateMissing<T>(p: Promise<T>): Promise<T | null> {
    try {
        return await p
    } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
            return null
        }
        throw err
    }
}

export function OverviewClient(): React.ReactElement {
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!
    const user = useSessionUser()

    // The overview is its own concierge surface — fleet-wide, not
    // agent-specific. Drop a sensible page kind + agent so the dock's
    // context envelope makes sense.
    useSetDockPage({ kind: 'agent-list' })
    useSetDockConciergeAgent({ slug: 'agent-concierge' })

    // Fleet rollup + agent count drive the small stat strip + jump-card
    // subtitle. Both are best-effort — a 404 (Phase C endpoints not
    // shipped, or no agents yet) renders the overview with `null`
    // values instead of an error page.
    const agents = useResource(() => tolerateMissing(listAgents(teamId)), [teamId])
    const fleet = useResource(() => tolerateMissing(getFleetStats(teamId)), [teamId])

    return (
        <Overview
            displayName={user?.firstName ?? null}
            fleetStats={fleet.data ?? null}
            agentCount={agents.data?.length}
        />
    )
}
