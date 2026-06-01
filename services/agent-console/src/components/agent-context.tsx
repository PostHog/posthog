/**
 * Per-agent context shared across the `/agents/[slug]/*` route segments.
 *
 * The `[slug]/layout.tsx` does the fetches once (agent + revisions) and
 * provides them through this context. Child segments (`overview`,
 * `configuration`, `connections`, `sessions`, `memory`) read from
 * `useAgent()` / `useRevisions()` so there's no per-tab refetch and a
 * tab switch is a pure soft-nav with no data flash.
 *
 * Mutations (revision lifecycle, env edits) bump the shared `reload`
 * counter via `useAgentReload()` so dependent fetches re-run; the
 * provider's `useResource` keys off it and refetches the layout-owned
 * data centrally.
 */

'use client'

import { createContext, useCallback, useContext, useState } from 'react'

import type { AgentApplicationFixture, AgentRevisionFixture } from '@posthog/agent-chat/fixtures'

import { useSessionTeamId } from '@/components/session-context'
import { getAgent, listRevisions } from '@/lib/apiClient'
import { useResource } from '@/lib/useResource'

interface AgentBundle {
    agent: AgentApplicationFixture
    revisions: AgentRevisionFixture[]
    /** Increment to invalidate the agent + revisions fetches in this provider. */
    bumpReload: () => void
}

const AgentCtx = createContext<AgentBundle | null>(null)

export interface AgentProviderProps {
    slug: string
    /** Shown while the initial fetch is pending. */
    fallback: React.ReactNode
    /** Rendered when the agent 404s. The route segment maps this to `notFound()`. */
    notFoundFallback: React.ReactNode
    /** Rendered on non-404 fetch failures. */
    errorFallback: (err: Error) => React.ReactNode
    children: React.ReactNode
}

export function AgentProvider({
    slug,
    fallback,
    notFoundFallback,
    errorFallback,
    children,
}: AgentProviderProps): React.ReactElement {
    const teamId = useSessionTeamId()!
    const [reload, setReload] = useState(0)
    const bumpReload = useCallback(() => setReload((n) => n + 1), [])

    const agent = useResource(() => getAgent(teamId, slug), [teamId, slug, reload])
    const revisions = useResource(() => listRevisions(teamId, slug), [teamId, slug, reload])

    if (agent.error) {
        // ApiError carries `status`; this lets the layout map 404 to
        // `notFound()` without the provider importing Next.js navigation.
        const status = (agent.error as { status?: number }).status
        if (status === 404) {
            return <>{notFoundFallback}</>
        }
        return <>{errorFallback(agent.error)}</>
    }
    if (!agent.data || (!revisions.data && !revisions.error)) {
        return <>{fallback}</>
    }

    // Revisions failure is non-fatal — render with empty list. The
    // configuration tab will show its own empty state.
    const value: AgentBundle = {
        agent: agent.data,
        revisions: revisions.data ?? [],
        bumpReload,
    }
    return <AgentCtx.Provider value={value}>{children}</AgentCtx.Provider>
}

export function useAgent(): AgentApplicationFixture {
    const ctx = useContext(AgentCtx)
    if (!ctx) {
        throw new Error('useAgent must be used inside <AgentProvider> (i.e. under /agents/[slug]/layout)')
    }
    return ctx.agent
}

export function useRevisions(): AgentRevisionFixture[] {
    const ctx = useContext(AgentCtx)
    if (!ctx) {
        throw new Error('useRevisions must be used inside <AgentProvider>')
    }
    return ctx.revisions
}

export function useAgentReload(): () => void {
    const ctx = useContext(AgentCtx)
    if (!ctx) {
        throw new Error('useAgentReload must be used inside <AgentProvider>')
    }
    return ctx.bumpReload
}
