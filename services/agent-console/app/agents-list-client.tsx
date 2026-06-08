'use client'

import { useRouter } from 'next/navigation'
import { useCallback, useMemo } from 'react'

import type { AgentApplicationFixture, AgentStats, FleetStats } from '@posthog/agent-chat/fixtures'

import { useSetDockConciergeAgent, useSetDockPage } from '@/components/dock-context'
import { AgentsListSkeleton } from '@/components/PageSkeletons'
import { useSessionTeamId } from '@/components/session-context'
import { ApiError, getAgentStats, getFleetStats, listAgents } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'
import { AgentsList } from '@/screens/AgentsList'

const EMPTY_FLEET_STATS: FleetStats = {
    liveSessionCount: 0,
    sessions24hCount: 0,
    spend24hUsd: 0,
    approvalsPendingCount: 0,
}

/** Treat a 404 as "this endpoint isn't built yet" and return a default. */
async function tolerateMissing<T>(p: Promise<T>, fallback: T): Promise<T> {
    try {
        return await p
    } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
            return fallback
        }
        throw err
    }
}

/**
 * Fan out across the non-archived agents and roll up each agent's
 * stats card. The janitor's per-application endpoint is cheap (one
 * JSONB sum + a count) so this is fine while the fleet has tens of
 * agents — swap for a bulk `aggregate_per_application` rollup if
 * teams start regularly carrying hundreds.
 */
async function fetchStatsBySlug(
    teamId: number,
    agents: AgentApplicationFixture[]
): Promise<Record<string, AgentStats>> {
    const active = agents.filter((a) => !a.archived)
    const entries = await Promise.all(
        active.map(async (a) => {
            const stats = await tolerateMissing<AgentStats | null>(getAgentStats(teamId, a.slug), null)
            return [a.slug, stats] as const
        })
    )
    const out: Record<string, AgentStats> = {}
    for (const [slug, stats] of entries) {
        if (stats) {
            out[slug] = stats
        }
    }
    return out
}

export function AgentsListClient(): React.ReactElement {
    const router = useRouter()
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!
    useSetDockPage({ kind: 'agent-list' })
    useSetDockConciergeAgent({ slug: 'agent-concierge' })

    // Poll the fleet dashboard — this is the "what's happening right now"
    // surface, so it refreshes on a short interval (visibility-aware, so a
    // backgrounded tab goes quiet and catches up on focus).
    const POLL_MS = 10_000
    const agents = useResource(() => listAgents(teamId), [teamId], { pollMs: POLL_MS })
    // Fleet endpoints are Phase C — tolerate 404 so the agents list still
    // renders against bare Django.
    const fleet = useResource(() => tolerateMissing(getFleetStats(teamId), EMPTY_FLEET_STATS), [teamId], {
        pollMs: POLL_MS,
    })

    const agentsData = agents.data
    const statsFactory = useCallback(
        async () => (agentsData ? fetchStatsBySlug(teamId, agentsData) : {}),
        [teamId, agentsData]
    )
    const stats = useResource<Record<string, AgentStats>>(
        statsFactory,
        // Recompute when the list of slugs changes — adding/removing an
        // agent should re-fan-out without waiting for the next poll tick.
        [teamId, agentsData?.map((a) => a.slug).join(',')],
        { pollMs: POLL_MS }
    )

    const error = agents.error ?? fleet.error ?? stats.error

    const onOpenAgent = useMemo(() => (slug: string) => router.push(`/agents/${slug}`), [router])

    if (error) {
        return <div className="px-6 py-6 text-sm text-destructive-foreground">Failed to load: {error.message}</div>
    }
    // Stale-while-revalidate: only block on the first load, not on
    // refetches triggered by bumpReload (otherwise lifecycle actions
    // flash the whole page back to a placeholder).
    if (!agents.data || !fleet.data || !stats.data) {
        return <AgentsListSkeleton />
    }

    return (
        <AgentsList agents={agents.data} fleetStats={fleet.data} statsBySlug={stats.data} onOpenAgent={onOpenAgent} />
    )
}
