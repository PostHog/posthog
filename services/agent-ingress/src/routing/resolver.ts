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

    async resolveBySlug(slug: string, opts?: { revisionId?: string }): Promise<ResolvedAgent | null> {
        const application = await this.opts.revisions.getApplicationBySlug(this.opts.teamId, slug)
        if (!application || application.archived) {
            return null
        }
        // Explicit revision_id override (used to invoke draft/ready revisions
        // for testing). The revision must belong to this application — anything
        // else is treated as a 404 so we don't leak revisions across apps.
        if (opts?.revisionId) {
            const override = await this.opts.revisions.getRevision(opts.revisionId)
            if (!override || override.application_id !== application.id || override.state === 'archived') {
                return null
            }
            return { application, revision: override }
        }
        if (!application.live_revision_id) {
            return null
        }
        const revision = await this.opts.revisions.getRevision(application.live_revision_id)
        if (!revision) {
            return null
        }
        return { application, revision }
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
