/**
 * Shared helper for triggers mounted under /agents/:slug. Routes pull the slug
 * from req.params first (set by the express mount); domain-mode falls back to
 * Host-header parsing.
 */

import { Request, Response } from 'express'

import { AmbiguousRevisionError, ResolvedAgent, RevisionResolver } from '../routing/resolver'

/**
 * Resolve the agent for a request, writing a 400 to `res` and returning null
 * when the URL's `<slug>-<revision-prefix>` form matches more than one
 * revision. The trigger should bail (`if (!resolved) return`) without writing
 * any further response — `res.headersSent` is set when this path fired.
 *
 * Async errors don't propagate cleanly through Express 4's middleware chain,
 * so we catch the ambiguity error here rather than relying on the error
 * middleware. Every other failure is a plain `null` (404 territory).
 */
export async function resolveAgent(
    resolver: RevisionResolver,
    req: Request,
    res: Response
): Promise<ResolvedAgent | null> {
    // Optional override that lets authoring flows invoke a specific revision
    // (draft / ready) instead of whatever's currently live. Accepted as either
    // a query param (?revision_id=...) or a header (x-agent-revision: ...).
    const revQuery = typeof req.query?.revision_id === 'string' ? req.query.revision_id : null
    const revHeader = req.headers['x-agent-revision']
    const revisionId = revQuery || (typeof revHeader === 'string' ? revHeader : null) || undefined

    const slug = typeof req.params?.slug === 'string' ? req.params.slug : null
    try {
        if (slug) {
            return await resolver.resolveBySlug(slug, { revisionId })
        }
        if (revisionId) {
            // Domain-mode + revision-override is ambiguous: there's no slug in the
            // path so we can't bound the override to a single application. Refuse
            // rather than silently picking the wrong agent.
            return null
        }
        return await resolver.resolveFromHostAndPath(req.headers.host, req.originalUrl || req.url || req.path)
    } catch (err) {
        if (err instanceof AmbiguousRevisionError) {
            res.status(400).json({
                error: 'ambiguous_revision',
                prefix: err.prefix,
                application_id: err.applicationId,
                candidates: err.candidates,
                detail: 'Multiple revisions match this prefix; re-issue with a longer prefix or pass ?revision_id.',
            })
            return null
        }
        throw err
    }
}

/**
 * The revision must declare a trigger of the given type. Otherwise return null
 * and let the caller 404. Mirrors the old "agent has only a slack trigger →
 * POST /run → 404" behavior — agents only accept the surfaces they opt into.
 */
export function hasTrigger(agent: ResolvedAgent, type: string): boolean {
    return agent.revision.spec.triggers.some((t) => t.type === type)
}
