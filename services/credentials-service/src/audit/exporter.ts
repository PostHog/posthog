// Sends audit rows to a PostHog project as `$credentials_access` events.
//
// Every pod runs the loop, but a session advisory lock makes one pod export at a time. A batch
// is selected with FOR UPDATE SKIP LOCKED and marked exported in the same transaction that
// holds it, so a failed send leaves the rows for the next tick. A send that succeeds but fails
// to commit sends the rows again, and the event uuid (the row id) lets PostHog drop the copy.

import https from 'node:https'
import type { Pool, PoolClient } from 'pg'

import type { ProxyAwareAgentOptions } from '../crypto/aws-kms'
import type { AuditExportConfig } from '../lib/config'
import { logger } from '../lib/logging'
import { auditExportedTotal } from './metrics'

export const AUDIT_EVENT = '$credentials_access'

/** Distinct id of every event. The user id is a property, so no person profile is created. */
export const AUDIT_DISTINCT_ID = 'credentials-service'

// Arbitrary constant, unique within this database.
export const EXPORT_LOCK_KEY = 7_201_001

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
export function toCaptureEvent(row: AuditRow, environment: string): CaptureEvent {
    return {
        event: AUDIT_EVENT,
        distinct_id: AUDIT_DISTINCT_ID,
        uuid: row.id,
        timestamp: row.occurred_at.toISOString(),
        properties: {
            $process_person_profile: false,
            environment,
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

/** A fetch-shaped POST over `node:https`. Node's fetch takes no agent, so it cannot use a proxy agent. */
export function agentFetch(agent: https.Agent, timeoutMs: number): typeof fetch {
    return ((url: URL, init: RequestInit) =>
        new Promise<Response>((resolve, reject) => {
            const req = https.request(
                url,
                {
                    method: init.method,
                    headers: init.headers as Record<string, string>,
                    agent,
                    signal: init.signal ?? undefined,
                },
                (res) => {
                    clearTimeout(timer)
                    // The promise is settled here, so a later reset only needs to not crash the process.
                    res.on('error', (err) => logger.debug('audit:export_response_error', { error: err.message }))
                    // The body is never read. Draining it frees the socket.
                    res.resume()
                    resolve(new Response(null, { status: res.statusCode ?? 502 }))
                }
            )
            // Neither the abort signal nor a socket timeout fires while the proxy holds the CONNECT
            // open without answering, because the request has no socket yet.
            const timer = setTimeout(() => req.destroy(new Error('capture request timed out')), timeoutMs)
            req.on('error', (err) => {
                clearTimeout(timer)
                reject(err)
            })
            req.end(init.body as string)
        })) as unknown as typeof fetch
}

/**
 * Sends direct by default. With `proxyUrl` it goes through the egress proxy, because Node's fetch
 * ignores the pod's HTTPS_PROXY.
 */
export function captureSender(config: AuditExportConfig, fetchFn?: typeof fetch): Sender {
    const url = new URL('/batch/', config.host)
    const doFetch =
        fetchFn ??
        (config.proxyUrl
            ? agentFetch(
                  new https.Agent({
                      keepAlive: true,
                      proxyEnv: { HTTPS_PROXY: config.proxyUrl },
                  } as ProxyAwareAgentOptions),
                  config.timeoutMs
              )
            : fetch)
    return async (events) => {
        const res = await doFetch(url, {
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
        private readonly batchSize: number,
        private readonly environment: string
    ) {}

    /** Ends the current pass after its batch, so shutdown does not wait for the whole backlog. */
    stop(): void {
        this.stopped = true
    }

    /** One pass: as the leader, exports until nothing waits or a send fails. */
    async tick(): Promise<TickResult> {
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
                await this.send(result.rows.map((row) => toCaptureEvent(row, this.environment)))
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
}
