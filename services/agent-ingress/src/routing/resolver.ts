/**
 * Map an inbound request to an AgentApplication + its live revision.
 *
 * Two routing modes:
 *   - "domain": resolve by Host header (`<slug>.agents.posthog.com`)
 *   - "path"  : resolve by path prefix (`/agents/<slug>/...`)
 */

import { jwtVerify } from 'jose'

import { AgentApplication, AgentRevision, RevisionStore } from '@posthog/agent-shared'

/**
 * JWT audience that Django mints on preview-proxy hops. The ingress only
 * accepts tokens carrying this audience — so a JWT minted for some other
 * PostHog feature (export rendering, livestream, …) can't be replayed here.
 */
const PREVIEW_TOKEN_AUDIENCE = 'posthog:agent_preview'

export type RoutingMode = 'domain' | 'path'

export interface ResolvedAgent {
    application: AgentApplication
    revision: AgentRevision
}

/**
 * Thrown by the resolver when a `<slug>-<revision-prefix>` URL is requested
 * and the prefix matches more than one revision under that application. The
 * ingress catches this and returns a 400 with the candidate ids so the caller
 * can re-issue with a longer prefix.
 */
export class AmbiguousRevisionError extends Error {
    constructor(
        readonly applicationId: string,
        readonly prefix: string,
        readonly candidates: string[]
    ) {
        super(`prefix "${prefix}" matches ${candidates.length} revisions on application ${applicationId}`)
        this.name = 'AmbiguousRevisionError'
    }
}

/**
 * Thrown when a non-live revision is invoked without a valid preview JWT.
 * Django mints the token on each proxy call (short-lived, bound to the
 * (application, revision) it's invoking). Captured tokens expire in seconds
 * and can't be replayed against a different draft. See
 * `docs/agent-platform/plans/draft-preview-auth.md`.
 */
export class MissingPreviewSecretError extends Error {
    constructor(readonly reason: string = 'missing_or_invalid_preview_token') {
        super(`non-live revision invoke requires a valid preview token (${reason})`)
        this.name = 'MissingPreviewSecretError'
    }
}

export interface ResolverOpts {
    revisions: RevisionStore
    mode: RoutingMode
    /** For domain mode: the suffix to strip from Host (e.g. ".agents.posthog.com"). */
    domainSuffix?: string
    /** For path mode: the prefix that precedes the slug (e.g. "/agents"). */
    pathPrefix?: string
    /** Team that owns all routed agents in this deployment. v1 = single tenant. */
    teamId: number
    /**
     * HMAC secret shared with Django. Django mints a short-lived JWT (aud =
     * `posthog:agent_preview`, claims `{ app, rev }`) and sends it as
     * `x-agent-preview-token` on every preview-proxy hop; the resolver
     * verifies signature + exp + claim-binding on non-live resolutions.
     * Leave undefined to bypass the gate (dev / harness path); production
     * wires `AGENT_PREVIEW_SECRET`.
     */
    previewSecret?: string
}

export class RevisionResolver {
    constructor(private readonly opts: ResolverOpts) {}

    async resolveFromHostAndPath(host: string | undefined, path: string): Promise<ResolvedAgent | null> {
        let slug: string | null = null
        if (this.opts.mode === 'domain' && host) {
            slug = this.extractSlugFromHost(host)
        } else if (this.opts.mode === 'path') {
            slug = this.extractSlugFromPath(path)
        }
        if (!slug) {
            return null
        }
        return this.resolveBySlug(slug)
    }

    async resolveBySlug(
        rawSlug: string,
        opts?: { revisionId?: string; providedToken?: string }
    ): Promise<ResolvedAgent | null> {
        const resolved = await this.resolveBySlugInner(rawSlug, opts?.revisionId)
        if (!resolved) {
            return null
        }
        await this.assertPreviewGate(resolved, opts?.providedToken)
        return resolved
    }

    private async resolveBySlugInner(rawSlug: string, revisionId?: string): Promise<ResolvedAgent | null> {
        // Explicit ?revision_id=<uuid> wins over everything. Look up the
        // verbatim slug + verify ownership.
        if (revisionId) {
            const application = await this.opts.revisions.getApplicationBySlug(this.opts.teamId, rawSlug)
            if (!application || application.archived) {
                return null
            }
            return this.resolveWithExplicitRevision(application, revisionId)
        }

        // Try `<slug>-<8..32 hex>` first. The prefix must be ≥ 8 hex chars to
        // avoid colliding with normal slugs that contain trailing hex (the
        // serializer already forbids trailing `-` so `slug-` followed by 8
        // hex chars is unambiguous if `<slug>` resolves to an application).
        const suffixMatch = rawSlug.match(/^(.+)-([0-9a-f]{8,32})$/i)
        if (suffixMatch) {
            const [, baseSlug, prefix] = suffixMatch
            const baseApp = await this.opts.revisions.getApplicationBySlug(this.opts.teamId, baseSlug)
            if (baseApp && !baseApp.archived) {
                const candidates = await this.opts.revisions.listRevisionsByIdPrefix(baseApp.id, prefix)
                const live = candidates.filter((c) => c.state !== 'archived')
                if (live.length === 1) {
                    return { application: baseApp, revision: live[0] }
                }
                if (live.length > 1) {
                    throw new AmbiguousRevisionError(
                        baseApp.id,
                        prefix,
                        live.map((c) => c.id)
                    )
                }
                // No prefix match: fall through to the verbatim slug lookup so
                // a slug that legitimately ends in 8 hex chars still works.
            }
        }

        const application = await this.opts.revisions.getApplicationBySlug(this.opts.teamId, rawSlug)
        if (!application || application.archived || !application.live_revision_id) {
            return null
        }
        const revision = await this.opts.revisions.getRevision(application.live_revision_id)
        if (!revision) {
            return null
        }
        return { application, revision }
    }

    private async resolveWithExplicitRevision(
        application: AgentApplication,
        revisionId: string
    ): Promise<ResolvedAgent | null> {
        const override = await this.opts.revisions.getRevision(revisionId)
        if (!override || override.application_id !== application.id || override.state === 'archived') {
            return null
        }
        return { application, revision: override }
    }

    /**
     * Refuse non-live invokes unless the request carries a valid preview JWT
     * signed with the shared secret. Token must (a) verify against the HMAC,
     * (b) carry the `posthog:agent_preview` audience, (c) not be expired, and
     * (d) carry `app` + `rev` claims that match the resolved revision. The
     * check is bypassed when `previewSecret` isn't configured (dev / harness
     * path).
     */
    private async assertPreviewGate(resolved: ResolvedAgent, providedToken: string | undefined): Promise<void> {
        if (!this.opts.previewSecret) {
            return
        }
        if (resolved.revision.id === resolved.application.live_revision_id) {
            return
        }
        if (!providedToken) {
            throw new MissingPreviewSecretError('missing_token')
        }
        const keyBytes = new TextEncoder().encode(this.opts.previewSecret)
        let payload: Record<string, unknown>
        try {
            const verified = await jwtVerify(providedToken, keyBytes, {
                audience: PREVIEW_TOKEN_AUDIENCE,
                algorithms: ['HS256'],
            })
            payload = verified.payload as Record<string, unknown>
        } catch (e) {
            // jose throws on bad signature / expired / wrong audience.
            throw new MissingPreviewSecretError(`token_verify_failed: ${(e as Error).message}`)
        }
        if (payload.app !== resolved.application.id) {
            throw new MissingPreviewSecretError('app_claim_mismatch')
        }
        if (payload.rev !== resolved.revision.id) {
            throw new MissingPreviewSecretError('rev_claim_mismatch')
        }
    }

    extractSlugFromHost(host: string): string | null {
        const hostNoPort = host.split(':')[0]
        const suffix = this.opts.domainSuffix
        if (suffix && hostNoPort.endsWith(suffix)) {
            return hostNoPort.slice(0, -suffix.length) || null
        }
        return null
    }

    extractSlugFromPath(path: string): string | null {
        const prefix = this.opts.pathPrefix ?? '/agents'
        if (!path.startsWith(prefix + '/')) {
            return null
        }
        const rest = path.slice(prefix.length + 1)
        const slug = rest.split('/')[0]
        return slug || null
    }
}
