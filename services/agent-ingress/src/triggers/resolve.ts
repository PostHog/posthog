/**
 * Shared helper for triggers mounted under /agents/:slug. Routes pull the slug
 * from req.params first (set by the express mount); domain-mode falls back to
 * Host-header parsing.
 */

import { Request } from 'express'

import { ResolvedAgent, RevisionResolver } from '../routing/resolver'

export async function resolveAgent(resolver: RevisionResolver, req: Request): Promise<ResolvedAgent | null> {
    // Optional override that lets authoring flows invoke a specific revision
    // (draft / ready) instead of whatever's currently live. Accepted as either
    // a query param (?revision_id=...) or a header (x-agent-revision: ...).
    const revQuery = typeof req.query?.revision_id === 'string' ? req.query.revision_id : null
    const revHeader = req.headers['x-agent-revision']
    const revisionId = revQuery || (typeof revHeader === 'string' ? revHeader : null) || undefined

    const slug = typeof req.params?.slug === 'string' ? req.params.slug : null
    if (slug) {
        return resolver.resolveBySlug(slug, { revisionId })
    }
    if (revisionId) {
        // Domain-mode + revision-override is ambiguous: there's no slug in the
        // path so we can't bound the override to a single application. Refuse
        // rather than silently picking the wrong agent.
        return null
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
