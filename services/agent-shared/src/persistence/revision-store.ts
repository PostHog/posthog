/**
 * AgentApplication / AgentRevision read+write contract. Production wires to
 * Django via internal HTTP (or direct PG read). Tests use the in-memory impl.
 */

import { AgentApplication, AgentRevision, AgentSpec, RevisionState } from '../spec/spec'

export interface RevisionStore {
    getApplication(applicationId: string): Promise<AgentApplication | null>
    getApplicationBySlug(teamId: number, slug: string): Promise<AgentApplication | null>
    listApplications(teamId: number): Promise<AgentApplication[]>
    createApplication(input: NewApplication): Promise<AgentApplication>
    archiveApplication(applicationId: string): Promise<void>

    getRevision(revisionId: string): Promise<AgentRevision | null>
    listRevisions(applicationId: string): Promise<AgentRevision[]>
    createRevision(input: NewRevision): Promise<AgentRevision>
    updateSpec(revisionId: string, spec: AgentSpec): Promise<void>
    setRevisionState(revisionId: string, state: RevisionState, sha256?: string): Promise<void>
    setLiveRevision(applicationId: string, revisionId: string): Promise<void>
}

export interface NewApplication {
    team_id: number
    slug: string
    name: string
    description: string
    encrypted_env?: string | null
}

export interface NewRevision {
    application_id: string
    parent_revision_id: string | null
    created_by_id: number | null
    bundle_uri: string
    spec: AgentSpec
}

export class MemoryRevisionStore implements RevisionStore {
    private readonly apps = new Map<string, AgentApplication>()
    private readonly revs = new Map<string, AgentRevision>()
    private nextId = 1

    private genId(prefix: string): string {
        return `${prefix}_${(this.nextId++).toString(36)}`
    }

    async getApplication(applicationId: string): Promise<AgentApplication | null> {
        return this.apps.get(applicationId) ?? null
    }

    async getApplicationBySlug(teamId: number, slug: string): Promise<AgentApplication | null> {
        for (const a of this.apps.values()) {
            if (a.team_id === teamId && a.slug === slug) {
                return a
            }
        }
        return null
    }

    async listApplications(teamId: number): Promise<AgentApplication[]> {
        return [...this.apps.values()].filter((a) => a.team_id === teamId && !a.archived)
    }

    async createApplication(input: NewApplication): Promise<AgentApplication> {
        const app: AgentApplication = {
            id: this.genId('app'),
            team_id: input.team_id,
            slug: input.slug,
            name: input.name,
            description: input.description,
            live_revision_id: null,
            archived: false,
            encrypted_env: input.encrypted_env ?? null,
        }
        this.apps.set(app.id, app)
        return app
    }

    async archiveApplication(applicationId: string): Promise<void> {
        const a = this.apps.get(applicationId)
        if (a) {
            a.archived = true
        }
    }

    async getRevision(revisionId: string): Promise<AgentRevision | null> {
        return this.revs.get(revisionId) ?? null
    }

    async listRevisions(applicationId: string): Promise<AgentRevision[]> {
        return [...this.revs.values()]
            .filter((r) => r.application_id === applicationId)
            .sort((a, b) => a.created_at.localeCompare(b.created_at))
    }

    async createRevision(input: NewRevision): Promise<AgentRevision> {
        const rev: AgentRevision = {
            id: this.genId('rev'),
            application_id: input.application_id,
            parent_revision_id: input.parent_revision_id,
            created_by_id: input.created_by_id,
            created_at: new Date().toISOString(),
            state: 'draft',
            bundle_uri: input.bundle_uri,
            bundle_sha256: null,
            spec: input.spec,
        }
        this.revs.set(rev.id, rev)
        return rev
    }

    async updateSpec(revisionId: string, spec: AgentSpec): Promise<void> {
        const r = this.revs.get(revisionId)
        if (!r) {
            return
        }
        if (r.state !== 'draft') {
            throw new Error(`revision ${revisionId} is not a draft`)
        }
        r.spec = spec
    }

    async setRevisionState(revisionId: string, state: RevisionState, sha256?: string): Promise<void> {
        const r = this.revs.get(revisionId)
        if (!r) {
            return
        }
        r.state = state
        if (sha256) {
            r.bundle_sha256 = sha256
        }
    }

    async setLiveRevision(applicationId: string, revisionId: string): Promise<void> {
        const a = this.apps.get(applicationId)
        if (a) {
            a.live_revision_id = revisionId
        }
    }
}
