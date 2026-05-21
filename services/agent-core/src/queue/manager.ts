import { Pool } from 'pg'
import { v7 as uuidv7 } from 'uuid'

import { logger } from '../logger'
import { createAgentPgPool } from '../postgres'
import { ManagerConfig, SessionJobInit, SessionJobInitSchema } from './types'

const DEFAULT_DEPTH_LIMIT = 1_000_000
const DEFAULT_DEPTH_CHECK_INTERVAL_MS = 10_000
const DEFAULT_MAX_STATE_BYTES = 1_048_576 // 1 MiB soft cap

export class SessionQueueManager {
    private pool: Pool
    private readonly depthLimit: number
    private readonly depthCheckIntervalMs: number
    private readonly maxStateByteSize: number
    private depthCheckPromise: Promise<boolean> | null = null
    private depthCheckExpiresAt = 0

    constructor(config: ManagerConfig) {
        this.pool = createAgentPgPool(config.pool, 10)
        this.depthLimit = config.depthLimit ?? DEFAULT_DEPTH_LIMIT
        this.depthCheckIntervalMs = config.depthCheckIntervalMs ?? DEFAULT_DEPTH_CHECK_INTERVAL_MS
        this.maxStateByteSize = config.maxStateByteSize ?? DEFAULT_MAX_STATE_BYTES
    }

    async connect(): Promise<void> {
        const client = await this.pool.connect()
        client.release()
    }

    async createJob(input: SessionJobInit): Promise<string> {
        const job = SessionJobInitSchema.parse(input)
        this.assertStateUnderCap(job.state)
        await this.insertGuard()

        const id = job.id ?? uuidv7()
        const now = new Date()
        const stateByteSize = job.state ? job.state.byteLength : null

        await this.pool.query(
            `INSERT INTO agent_sessions
             (id, team_id, application_id, revision_id, queue_name, status, scheduled, created,
              lock_id, last_heartbeat, janitor_touch_count, transition_count, last_transition,
              state, state_byte_size)
             VALUES ($1, $2, $3, $4, $5, 'available', $6, $7,
                     NULL, NULL, 0, 0, $7,
                     $8, $9)`,
            [
                id,
                job.teamId,
                job.applicationId ?? null,
                job.revisionId ?? null,
                job.queueName,
                job.scheduled ?? now,
                now,
                job.state ?? null,
                stateByteSize,
            ]
        )
        return id
    }

    async disconnect(): Promise<void> {
        await this.pool.end()
    }

    private assertStateUnderCap(state: Buffer | null | undefined): void {
        if (state && state.byteLength > this.maxStateByteSize) {
            throw new Error(
                `Session state too large (${state.byteLength} bytes, cap ${this.maxStateByteSize}); ` +
                    'offload conversation log to S3 and store only the pointer in state.'
            )
        }
    }

    private async insertGuard(): Promise<void> {
        if (await this.isFull()) {
            throw new Error(`Agent session queue is full (depth limit: ${this.depthLimit})`)
        }
    }

    private isFull(): Promise<boolean> {
        if (this.depthCheckPromise && Date.now() < this.depthCheckExpiresAt) {
            return this.depthCheckPromise
        }
        this.depthCheckPromise = this.queryDepth()
        this.depthCheckExpiresAt = Date.now() + this.depthCheckIntervalMs
        return this.depthCheckPromise
    }

    private async queryDepth(): Promise<boolean> {
        try {
            const result = await this.pool.query<{ count: string }>(
                `SELECT COUNT(*) AS count FROM agent_sessions
                 WHERE status = 'available' AND scheduled <= NOW()`
            )
            const count = parseInt(result.rows[0].count, 10)
            const full = count >= this.depthLimit
            if (full) {
                logger.warn('Agent session queue at capacity', { count, depthLimit: this.depthLimit })
            }
            return full
        } catch (e) {
            logger.error('Agent session queue depth check failed', { error: String(e) })
            return false
        }
    }
}
