/**
 * Postgres-backed SessionQueue. SELECT FOR UPDATE SKIP LOCKED for the claim.
 * Each row in `agent_session_v2` IS the queue entry; state transitions drive
 * lifecycle.
 *
 * The runner subprocess and the test process share the same table — claims
 * are at PG transaction granularity, so concurrent workers are safe.
 */

import type { Pool, PoolClient } from 'pg'

import { SessionQueue } from './queue'
import { AgentSession, ConversationMessage } from './spec'

export class PgSessionQueue implements SessionQueue {
    constructor(private readonly pool: Pool) {}

    async enqueue(session: AgentSession): Promise<void> {
        await this.pool.query(
            `INSERT INTO agent_session_v2
                (id, application_id, revision_id, team_id, external_key, state, conversation, created_at, updated_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
             ON CONFLICT (id) DO UPDATE SET
                state = EXCLUDED.state,
                conversation = EXCLUDED.conversation,
                updated_at = EXCLUDED.updated_at`,
            [
                session.id,
                session.application_id,
                session.revision_id,
                session.team_id,
                session.external_key,
                session.state,
                JSON.stringify(session.conversation),
                session.created_at,
                session.updated_at,
            ]
        )
    }

    async claim(timeoutMs: number): Promise<AgentSession | null> {
        const start = Date.now()
        while (Date.now() - start < timeoutMs) {
            const claimed = await this.claimOnce()
            if (claimed) {
                return claimed
            }
            await new Promise((r) => setTimeout(r, 50))
        }
        return null
    }

    private async claimOnce(): Promise<AgentSession | null> {
        const client: PoolClient = await this.pool.connect()
        try {
            await client.query('BEGIN')
            const sel = await client.query<{
                id: string
                application_id: string
                revision_id: string
                team_id: number
                external_key: string | null
                state: string
                conversation: unknown
                created_at: Date
                updated_at: Date
            }>(
                `SELECT id, application_id, revision_id, team_id, external_key, state,
                        conversation, created_at, updated_at
                 FROM agent_session_v2
                 WHERE state = 'queued'
                 ORDER BY created_at ASC
                 LIMIT 1
                 FOR UPDATE SKIP LOCKED`
            )
            if (sel.rowCount === 0) {
                await client.query('ROLLBACK')
                return null
            }
            const row = sel.rows[0]
            const now = new Date()
            await client.query(
                `UPDATE agent_session_v2 SET state = 'running', claimed_at = $2, updated_at = $2 WHERE id = $1`,
                [row.id, now]
            )
            await client.query('COMMIT')
            return rowToSession({ ...row, state: 'running', updated_at: now })
        } catch (err) {
            await client.query('ROLLBACK').catch(() => undefined)
            throw err
        } finally {
            client.release()
        }
    }

    async update(sessionId: string, patch: Partial<AgentSession>): Promise<void> {
        const sets: string[] = ['updated_at = NOW()']
        const params: unknown[] = [sessionId]
        let i = 2
        if (patch.state !== undefined) {
            sets.push(`state = $${i++}`)
            params.push(patch.state)
        }
        if (patch.conversation !== undefined) {
            sets.push(`conversation = $${i++}::jsonb`)
            params.push(JSON.stringify(patch.conversation))
        }
        if (patch.external_key !== undefined) {
            sets.push(`external_key = $${i++}`)
            params.push(patch.external_key)
        }
        await this.pool.query(`UPDATE agent_session_v2 SET ${sets.join(', ')} WHERE id = $1`, params)
    }

    async appendMessage(sessionId: string, msg: ConversationMessage): Promise<void> {
        await this.pool.query(
            `UPDATE agent_session_v2
             SET conversation = conversation || $2::jsonb,
                 updated_at = NOW()
             WHERE id = $1`,
            [sessionId, JSON.stringify([msg])]
        )
    }

    async get(sessionId: string): Promise<AgentSession | null> {
        const r = await this.pool.query(
            `SELECT id, application_id, revision_id, team_id, external_key, state, conversation, created_at, updated_at
             FROM agent_session_v2 WHERE id = $1`,
            [sessionId]
        )
        if (r.rowCount === 0) {
            return null
        }
        return rowToSession(r.rows[0])
    }

    async findByExternalKey(applicationId: string, externalKey: string): Promise<AgentSession | null> {
        // Return the most recently updated live one, if any.
        const r = await this.pool.query(
            `SELECT id, application_id, revision_id, team_id, external_key, state, conversation, created_at, updated_at
             FROM agent_session_v2
             WHERE application_id = $1 AND external_key = $2
             ORDER BY updated_at DESC
             LIMIT 1`,
            [applicationId, externalKey]
        )
        if (r.rowCount === 0) {
            return null
        }
        return rowToSession(r.rows[0])
    }

    /** Test helper — list all sessions for a given application. */
    async listForApplication(applicationId: string): Promise<AgentSession[]> {
        const r = await this.pool.query(
            `SELECT id, application_id, revision_id, team_id, external_key, state, conversation, created_at, updated_at
             FROM agent_session_v2
             WHERE application_id = $1
             ORDER BY created_at ASC`,
            [applicationId]
        )
        return r.rows.map(rowToSession)
    }
}

function rowToSession(row: {
    id: string
    application_id: string
    revision_id: string
    team_id: number
    external_key: string | null
    state: string
    conversation: unknown
    created_at: Date
    updated_at: Date
}): AgentSession {
    return {
        id: row.id,
        application_id: row.application_id,
        revision_id: row.revision_id,
        team_id: row.team_id,
        external_key: row.external_key,
        state: row.state as AgentSession['state'],
        conversation: Array.isArray(row.conversation) ? (row.conversation as AgentSession['conversation']) : [],
        created_at: row.created_at.toISOString(),
        updated_at: row.updated_at.toISOString(),
    }
}
