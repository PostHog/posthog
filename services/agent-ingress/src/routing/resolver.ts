/**
 * Map an inbound request to an AgentApplication + its live revision.
 *
 * Two routing modes:
 *   - "domain": resolve by Host header (`<slug>.agents.posthog.com`)
 *   - "path"  : resolve by path prefix (`/agents/<slug>/...`)
 */

import { AgentApplication, AgentRevision, RevisionStore } from '@posthog/agent-shared'

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

export interface ResolverOpts {
    revisions: RevisionStore
    mode: RoutingMode
    /** For domain mode: the suffix to strip from Host (e.g. ".agents.posthog.com"). */
    domainSuffix?: string
    /** For path mode: the prefix that precedes the slug (e.g. "/agents"). */
    pathPrefix?: string
    /** Team that owns all routed agents in this deployment. v1 = single tenant. */
    teamId: number
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

    async resolveBySlug(rawSlug: string, opts?: { revisionId?: string }): Promise<ResolvedAgent | null> {
        // Explicit ?revision_id=<uuid> wins over everything. Look up the
        // verbatim slug + verify ownership.
        if (opts?.revisionId) {
            const application = await this.opts.revisions.getApplicationBySlug(this.opts.teamId, rawSlug)
            if (!application || application.archived) {
                return null
            }
            return this.resolveWithExplicitRevision(application, opts.revisionId)
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
