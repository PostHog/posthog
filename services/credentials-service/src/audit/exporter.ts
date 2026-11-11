// Sends audit rows to a PostHog project as `$credentials_access` events.
//
// Every pod runs the loop, but a session advisory lock makes one pod export at a time. A batch
// is selected with FOR UPDATE SKIP LOCKED and marked exported in the same transaction that
// holds it, so a failed send leaves the rows for the next tick. A send that succeeds but fails
// to commit sends the rows again, and the event uuid (the row id) lets PostHog drop the copy.

import type { Pool, PoolClient } from 'pg'

import type { AuditExportConfig } from '../lib/config'
import { logger } from '../lib/logging'
import { auditExportLagSeconds, auditExportedTotal } from './metrics'

export const AUDIT_EVENT = '$credentials_access'

/** Distinct id of every event. The user id is a property, so no person profile is created. */
export const AUDIT_DISTINCT_ID = 'credentials-service'

// Arbitrary constants, unique within this database.
export const EXPORT_LOCK_KEY = 7_201_001
export const RETENTION_LOCK_KEY = 7_201_002

interface AuditRow {
    id: string
    occurred_at: Date
    /** Microseconds since the epoch. A JS Date keeps milliseconds only, so it cannot name the row. */
    occurred_at_us: string
    deployment: string
    caller: string | null
    user_id: string | null
    owner_type: string | null
    owner_id: string | null
    integration_id: string | null
    kind: string | null
    operation: string
    fields: string[]
    outcome: string
    request_id: string | null
}

export interface CaptureEvent {
    event: typeof AUDIT_EVENT
    distinct_id: typeof AUDIT_DISTINCT_ID
    uuid: string
    timestamp: string
    properties: Record<string, unknown>
}

/**
 * Only these columns are ever selected. `details` and `jti` stay out of the event on purpose.
 * `fields` holds secret key names, never values.
 */
export function toCaptureEvent(row: AuditRow): CaptureEvent {
    return {
        event: AUDIT_EVENT,
        distinct_id: AUDIT_DISTINCT_ID,
        uuid: row.id,
        timestamp: row.occurred_at.toISOString(),
        properties: {
            $process_person_profile: false,
            deployment: row.deployment,
            caller: row.caller,
            user_id: row.user_id === null ? null : Number(row.user_id),
            owner_type: row.owner_type,
            owner_id: row.owner_id === null ? null : Number(row.owner_id),
            integration_id: row.integration_id,
            kind: row.kind,
            operation: row.operation,
            fields: row.fields,
            outcome: row.outcome,
            request_id: row.request_id,
        },
    }
}

export type TickResult = 'idle' | 'exported' | 'not_leader' | 'failed'

export type Sender = (events: CaptureEvent[]) => Promise<void>

/** Plain fetch, so it follows the pod's own proxy handling: direct unless Node is told to use the env proxy. */
export function captureSender(config: AuditExportConfig, fetchFn: typeof fetch = fetch): Sender {
    const url = new URL('/batch/', config.host)
    return async (events) => {
        const res = await fetchFn(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_key: config.apiKey, batch: events }),
            signal: AbortSignal.timeout(config.timeoutMs),
        })
        // Cancel the body so the connection is freed whatever the status.
        await res.body?.cancel().catch(() => undefined)
        if (!res.ok) {
            // The body is left out of the error: it could echo the request.
            throw new Error(`capture answered ${res.status}`)
        }
    }
}

export class AuditExporter {
    private stopped = false

    constructor(
        private readonly pool: Pool,
        private readonly send: Sender,
        private readonly batchSize: number
    ) {}

    /** Ends the current pass after its batch, so shutdown does not wait for the whole backlog. */
    stop(): void {
        this.stopped = true
    }

    /** One pass: updates the lag gauge, then, as the leader, exports until nothing waits or a send fails. */
    async tick(): Promise<TickResult> {
        await this.updateLag()
        const client = await this.pool.connect()
        // A checked-out client has no error listener, so a dropped connection during a send
        // would otherwise be an uncaught 'error' event.
        let clientError: Error | undefined
        const onError = (err: Error): void => {
            clientError = err
        }
        client.on('error', onError)
        let locked = false
        try {
            const lock = await client.query('SELECT pg_try_advisory_lock($1) AS locked', [EXPORT_LOCK_KEY])
            locked = lock.rows[0].locked === true
            if (!locked) {
                return 'not_leader'
            }
            let exported = 0
            while (!this.stopped) {
                const count = await this.exportBatch(client)
                if (count === 0) {
                    return exported > 0 ? 'exported' : 'idle'
                }
                exported += count
            }
            return exported > 0 ? 'exported' : 'idle'
        } catch (err) {
            logger.error('audit:export_failed', { error: err instanceof Error ? err.message : String(err) })
            return 'failed'
        } finally {
            if (locked && !clientError) {
                await client.query('SELECT pg_advisory_unlock($1)', [EXPORT_LOCK_KEY]).catch(() => undefined)
            }
            if (clientError) {
                // Released with its error, so the pool drops it. The listener stays for late errors.
                client.release(clientError)
            } else {
                client.removeListener('error', onError)
                client.release()
            }
        }
    }

    private async exportBatch(client: PoolClient): Promise<number> {
        await client.query('BEGIN')
        try {
            const result = await client.query<AuditRow>(
                `SELECT id, occurred_at, (extract(epoch FROM occurred_at) * 1000000)::bigint AS occurred_at_us, deployment, caller, user_id, owner_type, owner_id, integration_id, kind,
                        operation, fields, outcome, request_id
                 FROM audit_log
                 WHERE exported_at IS NULL
                 ORDER BY occurred_at
                 LIMIT $1
                 FOR UPDATE SKIP LOCKED`,
                [this.batchSize]
            )
            if (result.rows.length === 0) {
                await client.query('ROLLBACK')
                return 0
            }
            try {
                await this.send(result.rows.map(toCaptureEvent))
            } catch (err) {
                auditExportedTotal.labels({ outcome: 'failed' }).inc(result.rows.length)
                throw err
            }
            const marked = await client.query(
                // Marks by primary key, with the values the select returned. Integer microseconds
                // name the same instant exactly, with no text parsing.
                `UPDATE audit_log AS a SET exported_at = now()
                 FROM unnest($1::bigint[], $2::uuid[]) AS b(occurred_at_us, id)
                 WHERE a.id = b.id
                   AND a.occurred_at = timestamptz 'epoch' + b.occurred_at_us * interval '1 microsecond'`,
                [result.rows.map((row) => row.occurred_at_us), result.rows.map((row) => row.id)]
            )
            // A row that stays unmarked would be selected and sent again on every pass.
            if (marked.rowCount !== result.rows.length) {
                throw new Error(`marked ${marked.rowCount} of ${result.rows.length} audit rows as exported`)
            }
            await client.query('COMMIT')
            auditExportedTotal.labels({ outcome: 'sent' }).inc(result.rows.length)
            return result.rows.length
        } catch (err) {
            await client.query('ROLLBACK').catch(() => undefined)
            throw err
        }
    }

    private async updateLag(): Promise<void> {
        try {
            const result = await this.pool.query(
                `SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(occurred_at)), 0) AS lag
                 FROM audit_log WHERE exported_at IS NULL`
            )
            auditExportLagSeconds.set(Number(result.rows[0].lag))
        } catch (err) {
            logger.warn('audit:lag_query_failed', { error: err instanceof Error ? err.message : String(err) })
        }
    }
}
