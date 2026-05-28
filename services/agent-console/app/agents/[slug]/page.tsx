/**
 * `/agents/<slug>` — agent overview. Read panel only; the chat dock
 * lives in the app shell and gets its context from the client wrapper.
 */

import { notFound } from 'next/navigation'

import { weeklyDigestBundle } from '@posthog/agent-chat/fixtures'

import { getAgentBySlug, getAgentStats, listRevisions, listSessionsForAgent } from '@/lib/mockApi'

import { AgentDetailClient } from './agent-detail-client'

export default async function AgentDetailPage({
    params,
}: {
    params: Promise<{ slug: string }>
}): Promise<React.ReactElement> {
    const { slug } = await params
    const agent = await getAgentBySlug(slug)
    if (!agent) {
        notFound()
    }
    const [revisions, stats, sessions] = await Promise.all([
        listRevisions(agent.id),
        getAgentStats(agent.id),
        listSessionsForAgent(agent.id),
    ])
    // v0 — bundle is fixture data shared across all revisions for the slug;
    // v0.1 fetches per-revision via the janitor.
    return (
        <AgentDetailClient
            agent={agent}
            revisions={revisions}
            bundle={weeklyDigestBundle}
            stats={stats}
            sessions={sessions}
        />
    )
}
