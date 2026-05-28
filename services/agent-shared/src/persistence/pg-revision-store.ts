/**
 * Postgres-backed RevisionStore. Mirrors MemoryRevisionStore's behavior exactly
 * — spec edits only allowed in draft, etc.
 */

import type { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'

import { AgentApplication, AgentRevision, AgentSpec, AgentSpecSchema, RevisionState } from '../spec/spec'
import { NewApplication, NewRevision, RevisionStore } from './revision-store'

export class PgRevisionStore implements RevisionStore {
    constructor(private readonly pool: Pool) {}

    async getApplication(applicationId: string): Promise<AgentApplication | null> {
        const r = await this.pool.query(
            `SELECT id, team_id, slug, name, description, encrypted_env, live_revision_id, archived
             FROM agent_application WHERE id = $1`,
            [applicationId]
        )
        return r.rowCount === 0 ? null : rowToApp(r.rows[0])
    }

    async getApplicationBySlug(teamId: number, slug: string): Promise<AgentApplication | null> {
        const r = await this.pool.query(
            `SELECT id, team_id, slug, name, description, encrypted_env, live_revision_id, archived
             FROM agent_application WHERE team_id = $1 AND slug = $2 AND archived = FALSE`,
            [teamId, slug]
        )
        return r.rowCount === 0 ? null : rowToApp(r.rows[0])
    }

    async listApplications(teamId: number): Promise<AgentApplication[]> {
        const r = await this.pool.query(
            `SELECT id, team_id, slug, name, description, encrypted_env, live_revision_id, archived
             FROM agent_application WHERE team_id = $1 AND archived = FALSE
             ORDER BY created_at ASC`,
            [teamId]
        )
        return r.rows.map(rowToApp)
    }

    async createApplication(input: NewApplication): Promise<AgentApplication> {
        const id = uuidv4()
        await this.pool.query(
            `INSERT INTO agent_application (id, team_id, slug, name, description, encrypted_env)
             VALUES ($1, $2, $3, $4, $5, $6)`,
            [id, input.team_id, input.slug, input.name, input.description, input.encrypted_env ?? null]
        )
        const r = await this.getApplication(id)
        if (!r) {
            throw new Error('created application not found')
        }
        return r
    }

    async archiveApplication(applicationId: string): Promise<void> {
        await this.pool.query(`UPDATE agent_application SET archived = TRUE, updated_at = NOW() WHERE id = $1`, [
            applicationId,
        ])
    }

    async getRevision(revisionId: string): Promise<AgentRevision | null> {
        const r = await this.pool.query(
            `SELECT id, application_id, parent_revision_id, created_by_id, created_at, state,
                    bundle_uri, bundle_sha256, spec
             FROM agent_revision WHERE id = $1`,
            [revisionId]
        )
        return r.rowCount === 0 ? null : rowToRev(r.rows[0])
    }

    async listRevisions(applicationId: string): Promise<AgentRevision[]> {
        const r = await this.pool.query(
            `SELECT id, application_id, parent_revision_id, created_by_id, created_at, state,
                    bundle_uri, bundle_sha256, spec
             FROM agent_revision WHERE application_id = $1
             ORDER BY created_at ASC`,
            [applicationId]
        )
        return r.rows.map(rowToRev)
    }

    async listRevisionsByIdPrefix(applicationId: string, idPrefix: string): Promise<AgentRevision[]> {
        // Strip dashes so the prefix can match the dash-less form (`019e6f25`)
        // or the dashed form (`019e6f25-0185`) — Postgres uuid::text always
        // emits the dashed canonical, so we compare on `replace(id::text, '-', '')`.
        // The functional comparison won't use the PK index but the row count
        // per app is small enough (tens of revs) that a Seq Scan within one
        // application_id is fine.
        const needle = idPrefix.replace(/-/g, '').toLowerCase()
        if (needle.length === 0) {
            return []
        }
        const r = await this.pool.query(
            `SELECT id, application_id, parent_revision_id, created_by_id, created_at, state,
                    bundle_uri, bundle_sha256, spec
             FROM agent_revision
             WHERE application_id = $1
               AND replace(lower(id::text), '-', '') LIKE $2 || '%'`,
            [applicationId, needle]
        )
        return r.rows.map(rowToRev)
    }

    async createRevision(input: NewRevision): Promise<AgentRevision> {
        const id = uuidv4()
        await this.pool.query(
            `INSERT INTO agent_revision
                (id, application_id, parent_revision_id, created_by_id, bundle_uri, spec)
             VALUES ($1, $2, $3, $4, $5, $6::jsonb)`,
            [
                id,
                input.application_id,
                input.parent_revision_id,
                input.created_by_id,
                input.bundle_uri,
                JSON.stringify(input.spec),
            ]
        )
        const r = await this.getRevision(id)
        if (!r) {
            throw new Error('created revision not found')
        }
        return r
    }

    async updateSpec(revisionId: string, spec: AgentSpec): Promise<void> {
        const cur = await this.getRevision(revisionId)
        if (!cur) {
            return
        }
        if (cur.state !== 'draft') {
            throw new Error(`revision ${revisionId} is not a draft`)
        }
        await this.pool.query(`UPDATE agent_revision SET spec = $2::jsonb WHERE id = $1`, [
            revisionId,
            JSON.stringify(spec),
        ])
    }

    async setRevisionState(revisionId: string, state: RevisionState, sha256?: string): Promise<void> {
        if (sha256 !== undefined) {
            await this.pool.query(`UPDATE agent_revision SET state = $2, bundle_sha256 = $3 WHERE id = $1`, [
                revisionId,
                state,
                sha256,
            ])
        } else {
            await this.pool.query(`UPDATE agent_revision SET state = $2 WHERE id = $1`, [revisionId, state])
        }
    }

    async setLiveRevision(applicationId: string, revisionId: string): Promise<void> {
        await this.pool.query(`UPDATE agent_application SET live_revision_id = $2, updated_at = NOW() WHERE id = $1`, [
            applicationId,
            revisionId,
        ])
    }
}

function rowToApp(row: {
    id: string
    team_id: number
    slug: string
    name: string
    description: string
    encrypted_env: string | null
    live_revision_id: string | null
    archived: boolean
}): AgentApplication {
    return {
        id: row.id,
        team_id: row.team_id,
        slug: row.slug,
        name: row.name,
        description: row.description,
        live_revision_id: row.live_revision_id,
        archived: row.archived,
        encrypted_env: row.encrypted_env,
    }
}

function rowToRev(row: {
    id: string
    application_id: string
    parent_revision_id: string | null
    created_by_id: number | null
    created_at: Date
    state: string
    bundle_uri: string
    bundle_sha256: string | null
    spec: unknown
}): AgentRevision {
    return {
        id: row.id,
        application_id: row.application_id,
        parent_revision_id: row.parent_revision_id,
        created_by_id: row.created_by_id,
        created_at: row.created_at.toISOString(),
        state: row.state as RevisionState,
        bundle_uri: row.bundle_uri,
        bundle_sha256: row.bundle_sha256,
        spec: AgentSpecSchema.parse(row.spec ?? {}),
    }
}
