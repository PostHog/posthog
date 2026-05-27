import type { Principal } from '@repo/ass-server/types'
import { DateTime } from 'luxon'
import { z } from 'zod'

export type SessionStatus = 'available' | 'running' | 'completed' | 'failed' | 'canceled'

export interface PoolConfig {
    dbUrl: string
    maxConnections?: number
    idleTimeoutMs?: number
    /** See `createAgentPgPool`. Tests turn this on so jest workers exit cleanly. */
    allowExitOnIdle?: boolean
}

const uuidSchema = z.string().uuid()

// Principal is validated as `unknown` at zod parse time — its shape is the
// canonical `Principal` discriminated union owned by ass-server, and we don't
// want this schema to second-guess that. The caller (agent-ingress) supplies
// a value `route()` already produced, so the type is trustworthy here even
// though we accept it untyped at the schema boundary.
export const SessionJobInitSchema = z.object({
    id: uuidSchema.optional(),
    teamId: z.number().int(),
    applicationId: uuidSchema.nullish(),
    revisionId: uuidSchema.nullish(),
    queueName: z.string().min(1),
    scheduled: z.date().optional(),
    state: z.instanceof(Buffer).nullish(),
    principal: z.unknown().nullish(),
})

export type SessionJobInit = Omit<z.infer<typeof SessionJobInitSchema>, 'principal'> & {
    /**
     * Caller principal stamped at ingress (Layer 1 + Layer 2 of
     * agent-stack/docs/auth-and-identity.md). Persisted on the session row
     * as a JSONB blob; agent-ingress reads it back for strict-match on
     * `/listen` / `/send` / `/cancel`.
     */
    principal?: Principal | null
}

export const RescheduleOptionsSchema = z.object({
    scheduledAt: z.date().optional(),
    state: z.instanceof(Buffer).nullish(),
})

export type RescheduleOptions = z.infer<typeof RescheduleOptionsSchema>

export interface DequeuedSessionJob {
    readonly id: string
    readonly teamId: number
    readonly applicationId: string | null
    readonly revisionId: string | null
    readonly queueName: string
    readonly scheduled: DateTime
    readonly created: DateTime
    readonly transitionCount: number
    readonly state: Buffer | null
    /**
     * Caller principal stamped at ingress (Layer 1+2 of agent-stack's
     * docs/auth-and-identity.md). Returned by the dequeue path so the worker
     * can thread it into the executor's job context — the executor / model
     * / tools can then see who the request is acting on behalf of.
     */
    readonly principal: Principal | null

    ack(): Promise<void>
    fail(): Promise<void>
    reschedule(options?: RescheduleOptions): Promise<void>
    cancel(): Promise<void>
    heartbeat(): Promise<void>
}

export interface ManagerConfig {
    pool: PoolConfig
    depthLimit?: number
    depthCheckIntervalMs?: number
    /** Soft cap on serialized SDK state stored inline. Larger payloads should be offloaded. */
    maxStateByteSize?: number
}

export interface WorkerConfig {
    pool: PoolConfig
    queueName: string
    /** Max jobs in flight at any one time. Doubles as the per-round dequeue limit
     *  (we only fetch `concurrency - inFlight` rows). Default 8. */
    concurrency?: number
    /** Sleep between dequeue rounds when the queue is empty. Default 50ms. */
    pollDelayMs?: number
    /** `isHealthy()` threshold: max age of the last fetcher tick before we report
     *  unhealthy. In-flight work also counts as healthy (we may be parked on a
     *  slot, which is fine). Default 30_000ms. */
    heartbeatTimeoutMs?: number
    /** Interval at which the worker pings `last_heartbeat` on each in-flight row.
     *  Auto-started when a job enters the handler, auto-stopped when it settles.
     *  Set to 0 to disable. Default 5_000ms. */
    heartbeatIntervalMs?: number
    /** On `disconnect()`, max time to wait for in-flight handlers to drain before
     *  forcefully closing the pool. Default 30_000ms. */
    drainTimeoutMs?: number
}

export interface JanitorConfig {
    pool: PoolConfig
    cleanupBatchSize?: number
    cleanupIntervalMs?: number
    stallTimeoutMs?: number
    maxTouchCount?: number
    cleanupGraceMs?: number
}

export interface CleanupResult {
    deleted: number
    stalled: number
    poisoned: number
    depths: Map<string, number>
}
