import { Pool } from 'pg'
import { Counter, Gauge } from 'prom-client'

import { logger } from '../logger'
import { createAgentPgPool } from '../postgres'
import { CleanupResult, JanitorConfig } from './types'

const janitorStalledCounter = new Counter({
    name: 'agent_core_janitor_stalled',
    help: 'Number of stalled agent sessions reset by the janitor',
})

const janitorPoisonedCounter = new Counter({
    name: 'agent_core_janitor_poisoned',
    help: 'Number of poison pill agent sessions failed by the janitor',
})

const janitorRunCounter = new Counter({
    name: 'agent_core_janitor_runs',
    help: 'Number of agent session janitor runs completed',
})

const queueDepthGauge = new Gauge({
    name: 'agent_core_queue_depth',
    help: 'Number of available agent sessions per queue',
    labelNames: ['queue'],
})

export class SessionQueueJanitor {
    private pool: Pool
    private intervalHandle: ReturnType<typeof setInterval> | null = null

    private readonly cleanupBatchSize: number
    private readonly cleanupIntervalMs: number
    private readonly stallTimeoutMs: number
    private readonly maxTouchCount: number
    private readonly cleanupGraceMs: number

    constructor(config: JanitorConfig) {
        this.pool = createAgentPgPool(config.pool, 5)
        this.cleanupBatchSize = config.cleanupBatchSize ?? 10_000
        this.cleanupIntervalMs = config.cleanupIntervalMs ?? 10_000
        this.stallTimeoutMs = config.stallTimeoutMs ?? 30_000
        this.maxTouchCount = config.maxTouchCount ?? 3
        this.cleanupGraceMs = config.cleanupGraceMs ?? 10_000
    }

    async start(): Promise<void> {
        const client = await this.pool.connect()
        client.release()

        this.intervalHandle = setInterval(() => {
            this.runOnce().catch((err) => {
                logger.error('SessionQueueJanitor run error', { error: String(err) })
            })
        }, this.cleanupIntervalMs)

        await this.runOnce()
    }

    async runOnce(): Promise<CleanupResult> {
        const deleted = await this.cleanupTerminalJobs()
        const poisoned = await this.failPoisonPills()
        const stalled = await this.resetStalledJobs()
        const depths = await this.measureQueueDepths()

        janitorRunCounter.inc()

        return { deleted, stalled, poisoned, depths }
    }

    private async cleanupTerminalJobs(): Promise<number> {
        // Terminal sessions are retained indefinitely — they're the audit trail
        // and the source of truth for the session list UI. The janitor only
        // handles stall recovery and poison-pill detection, not deletion.
        return 0
    }

    private async failPoisonPills(): Promise<number> {
        const heartbeatCutoff = new Date(Date.now() - this.stallTimeoutMs)
        const result = await this.pool.query(
            `UPDATE agent_sessions
             SET status = 'failed', lock_id = NULL, last_heartbeat = NULL,
                 last_transition = NOW(), transition_count = transition_count + 1
             WHERE id IN (
                 SELECT id
                 FROM agent_sessions
                 WHERE status = 'running'
                   AND COALESCE(last_heartbeat, $1) <= $1
                   AND janitor_touch_count >= $2
                 FOR UPDATE SKIP LOCKED
             )`,
            [heartbeatCutoff, this.maxTouchCount]
        )
        const count = result.rowCount ?? 0
        if (count > 0) {
            janitorPoisonedCounter.inc(count)
            logger.warn('SessionQueueJanitor failed poison-pill sessions', { count })
        }
        return count
    }

    private async resetStalledJobs(): Promise<number> {
        const heartbeatCutoff = new Date(Date.now() - this.stallTimeoutMs)
        const result = await this.pool.query(
            `WITH stalled AS (
                SELECT id
                FROM agent_sessions
                WHERE status = 'running'
                  AND COALESCE(last_heartbeat, $1) <= $1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE agent_sessions
            SET status = 'available', lock_id = NULL, last_heartbeat = NULL,
                janitor_touch_count = janitor_touch_count + 1
            FROM stalled
            WHERE agent_sessions.id = stalled.id`,
            [heartbeatCutoff]
        )
        const count = result.rowCount ?? 0
        if (count > 0) {
            janitorStalledCounter.inc(count)
            logger.info('SessionQueueJanitor reset stalled sessions', { count })
        }
        return count
    }

    async measureQueueDepths(): Promise<Map<string, number>> {
        const result = await this.pool.query<{ queue_name: string; count: string }>(
            `SELECT queue_name, COUNT(*) as count
             FROM agent_sessions
             WHERE status = 'available' AND scheduled <= NOW()
             GROUP BY queue_name`
        )
        const depths = new Map<string, number>()
        for (const row of result.rows) {
            const count = parseInt(row.count, 10)
            depths.set(row.queue_name, count)
            queueDepthGauge.labels({ queue: row.queue_name }).set(count)
        }
        return depths
    }

    isRunning(): boolean {
        return this.intervalHandle !== null
    }

    async stop(): Promise<void> {
        if (this.intervalHandle) {
            clearInterval(this.intervalHandle)
            this.intervalHandle = null
        }
        await this.pool.end()
    }
}
