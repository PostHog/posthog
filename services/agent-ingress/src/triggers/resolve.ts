/**
 * Shared helper for triggers mounted under /agents/:slug. Routes pull the slug
 * from req.params first (set by the express mount); domain-mode falls back to
 * Host-header parsing.
 */

import { Request, Response } from 'express'

import { AmbiguousRevisionError, MissingPreviewSecretError, ResolvedAgent, RevisionResolver } from '../routing/resolver'

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
    // Short-lived JWT that Django mints per preview-proxy hop. The resolver
    // verifies it on non-live resolutions. Live calls don't need it. See
    // docs/agent-platform/plans/draft-preview-auth.md.
    const previewHeader = req.headers['x-agent-preview-token']
    const providedToken = typeof previewHeader === 'string' ? previewHeader : undefined

    const slug = typeof req.params?.slug === 'string' ? req.params.slug : null
    try {
        if (slug) {
            // In path mode the express mount captured `:slug` — that's already
            // the full `<slug>` or `<slug>-<rev-hex>` form. Resolver handles
            // both shapes.
            return await resolver.resolveBySlug(slug, { providedToken })
        }
        return await resolver.resolveFromHostAndPath(req.headers.host, req.originalUrl || req.url || req.path, {
            providedToken,
        })
    } catch (err) {
        if (err instanceof AmbiguousRevisionError) {
            res.status(400).json({
                error: 'ambiguous_revision',
                prefix: err.prefix,
                application_id: err.applicationId,
                candidates: err.candidates,
                detail: 'Multiple revisions match this prefix; re-issue with a longer prefix (up to the full 32-char revision hex).',
            })
            return null
        }
        if (err instanceof MissingPreviewSecretError) {
            res.status(401).json({
                error: 'preview_token_required',
                reason: err.reason,
                detail: 'Non-live revision invokes must come through the Django preview-proxy. Use POST /api/projects/<team>/agent_applications/<app>/preview-proxy/...',
            })
            return null
        }
        throw err
    }
}

/**
 * The revision must declare a trigger of the given type. Otherwise return false
 * and let the caller 404. Mirrors the old "agent has only a slack trigger →
 * POST /run → 404" behavior — agents only accept the surfaces they opt into.
 *
 * Defensive against malformed specs: a revision with no `triggers` field
 * shouldn't blow up here with "Cannot read property 'some' of undefined" and
 * 500. Treat it as "no triggers declared" → 404.
 */
export function hasTrigger(agent: ResolvedAgent, type: string): boolean {
    const triggers = agent.revision.spec?.triggers
    if (!Array.isArray(triggers)) {
        return false
    }
    return triggers.some((t) => t?.type === type)
}
