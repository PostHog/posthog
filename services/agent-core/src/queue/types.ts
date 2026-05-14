import { DateTime } from 'luxon'
import { z } from 'zod'

export type SessionStatus = 'available' | 'running' | 'completed' | 'failed' | 'canceled'

export interface PoolConfig {
    dbUrl: string
    maxConnections?: number
    idleTimeoutMs?: number
}

const uuidSchema = z.string().uuid()

export const SessionJobInitSchema = z.object({
    id: uuidSchema.optional(),
    teamId: z.number().int(),
    applicationId: uuidSchema.nullish(),
    revisionId: uuidSchema.nullish(),
    queueName: z.string().min(1),
    scheduled: z.date().optional(),
    state: z.instanceof(Buffer).nullish(),
})

export type SessionJobInit = z.infer<typeof SessionJobInitSchema>

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
    batchMaxSize?: number
    pollDelayMs?: number
    heartbeatTimeoutMs?: number
    includeEmptyBatches?: boolean
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
