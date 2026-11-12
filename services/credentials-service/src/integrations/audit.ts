// The access trail: one `audit_log` row per record a request returns or changes. A write stores
// its rows in its own transaction. A read hands them to `AuditQueue`, which writes them in
// batches and drops (and counts) rows when it is full, so a read never waits for the audit write.

import type { Pool } from 'pg'

import { type Queryable, query } from '../db/integrations'
import { logger } from '../lib/logging'
import { auditDroppedTotal, auditWrittenTotal } from './metrics'

const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g

export interface AuditActor {
    deployment: string
    caller: string
    userId: number | null
    jti: string
    requestId: string
}

export interface AuditEntry {
    actor: AuditActor
    operation: string
    outcome: string
    ownerType: string | null
    ownerId: number | null
    integrationId: string | null
    kind: string | null
    /** The secret keys that the request returned or changed. Never their values. */
    fields?: readonly string[]
    details?: Record<string, unknown>
}

/**
 * Writes one JSON log line per audit entry, with field names and never values. The runtime
 * database role cannot erase these lines, and the queue never drops them, so they are the
 * record that alerts and investigations trust.
 */
export function logAuditEntries(entries: readonly AuditEntry[]): void {
    for (const entry of entries) {
        logger.audit('integrations:audited', {
            deployment: entry.actor.deployment,
            caller: entry.actor.caller,
            user_id: entry.actor.userId,
            owner_type: entry.ownerType,
            owner_id: entry.ownerId,
            integration_id: entry.integrationId,
            kind: entry.kind,
            operation: entry.operation,
            outcome: entry.outcome,
            fields: entry.fields ?? [],
            request_id: entry.actor.requestId,
            jti: entry.actor.jti,
            details: entry.details ?? {},
        })
    }
}

export async function insertAuditRows(db: Queryable, entries: readonly AuditEntry[]): Promise<void> {
    if (entries.length === 0) {
        return
    }
    const occurredAt = new Date().toISOString()
    const rows = entries.map((entry) => ({
        occurred_at: occurredAt,
        deployment: entry.actor.deployment,
        caller: entry.actor.caller,
        user_id: entry.actor.userId,
        owner_type: entry.ownerType,
        owner_id: entry.ownerId,
        integration_id: entry.integrationId,
        kind: entry.kind,
        operation: entry.operation,
        fields: entry.fields ?? [],
        outcome: entry.outcome,
        request_id: entry.actor.requestId,
        jti: entry.actor.jti,
        details: entry.details ?? {},
    }))
    // Postgres refuses a NUL or a lone surrogate in jsonb, and one bad value would fail the whole batch.
    const payload = JSON.stringify(rows, (_key, value: unknown) =>
        typeof value === 'string' ? value.replaceAll('\u0000', '').replace(LONE_SURROGATE, '\uFFFD') : value
    )
    // One statement for the whole batch. jsonb_to_recordset turns each JSON array into a Postgres array.
    await query(
        db,
        `INSERT INTO audit_log
            (occurred_at, deployment, caller, user_id, owner_type, owner_id, integration_id, kind,
             operation, fields, outcome, request_id, jti, details)
         SELECT occurred_at, deployment, caller, user_id, owner_type, owner_id, integration_id, kind,
                operation, fields, outcome, request_id, jti, details
         FROM jsonb_to_recordset($1::jsonb) AS r(
            occurred_at timestamptz, deployment text, caller text, user_id bigint, owner_type text,
            owner_id bigint, integration_id uuid, kind text, operation text, fields text[], outcome text,
            request_id text, jti text, details jsonb)`,
        [payload]
    )
}

export interface AuditQueueOptions {
    maxPending?: number
    batchSize?: number
    flushIntervalMs?: number
}

export class AuditQueue {
    private pending: AuditEntry[] = []
    private timer: ReturnType<typeof setInterval> | undefined
    private flushing: Promise<void> | undefined
    private readonly maxPending: number
    private readonly batchSize: number
    private readonly flushIntervalMs: number

    constructor(
        private readonly pool: Pool,
        opts: AuditQueueOptions = {}
    ) {
        this.maxPending = opts.maxPending ?? 10_000
        this.batchSize = opts.batchSize ?? 500
        this.flushIntervalMs = opts.flushIntervalMs ?? 1_000
    }

    get size(): number {
        return this.pending.length
    }

    /**
     * Never blocks and never throws. Rows past the limit are dropped and counted. The stdout
     * line is written first and is never dropped.
     */
    enqueue(entries: readonly AuditEntry[]): void {
        logAuditEntries(entries)
        const room = Math.max(0, this.maxPending - this.pending.length)
        if (entries.length > room) {
            auditDroppedTotal.labels({ reason: 'queue_full' }).inc(entries.length - room)
        }
        this.pending.push(...entries.slice(0, room))
        if (this.pending.length >= this.batchSize) {
            void this.flush()
        }
    }

    start(): void {
        if (this.timer) {
            return
        }
        this.timer = setInterval(() => void this.flush(), this.flushIntervalMs)
        this.timer.unref()
    }

    /** Writes every pending row. A batch that fails is dropped and counted, not retried. */
    flush(): Promise<void> {
        if (!this.flushing) {
            this.flushing = this.drain().finally(() => {
                this.flushing = undefined
            })
        }
        return this.flushing
    }

    /** Stops the timer and writes what is left. */
    async stop(): Promise<void> {
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = undefined
        }
        await this.flush()
    }

    private async drain(): Promise<void> {
        while (this.pending.length > 0) {
            const batch = this.pending.splice(0, this.batchSize)
            try {
                await insertAuditRows(this.pool, batch)
                auditWrittenTotal.inc(batch.length)
            } catch (err) {
                auditDroppedTotal.labels({ reason: 'write_failed' }).inc(batch.length)
                logger.error('audit:write_failed', {
                    rows: batch.length,
                    error: err instanceof Error ? err.message : String(err),
                })
            }
        }
    }
}
