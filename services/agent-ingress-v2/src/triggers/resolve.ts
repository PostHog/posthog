/**
 * Shared helper for triggers mounted under /agents/:slug. Routes pull the slug
 * from req.params first (set by the express mount); domain-mode falls back to
 * Host-header parsing.
 */

import { Request } from 'express'

import { ResolvedAgent, RevisionResolver } from '../resolver'

export async function resolveAgent(resolver: RevisionResolver, req: Request): Promise<ResolvedAgent | null> {
    const slug = typeof req.params?.slug === 'string' ? req.params.slug : null
    if (slug) {
        return resolver.resolveBySlug(slug)
    }
    return resolver.resolveFromHostAndPath(req.headers.host, req.originalUrl || req.url || req.path)
}

/**
 * The revision must declare a trigger of the given type. Otherwise return null
 * and let the caller 404. Mirrors the old "agent has only a slack trigger →
 * POST /run → 404" behavior — agents only accept the surfaces they opt into.
 */
export function hasTrigger(agent: ResolvedAgent, type: string): boolean {
    return agent.revision.spec.triggers.some((t) => t.type === type)
}
