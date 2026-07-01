// SSE stream handler for task-run event streams.
//
// Ports products/tasks/backend/stream/sse.py (stream_task_run_events) to an
// async generator yielding SSE byte chunks. Wire protocol is byte-identical to
// the Python implementation: during cutover Django and this Node service read
// the SAME Redis stream and serve the SAME clients. Any drift corrupts live runs.
//
// SSE framing (format_sse_event — byte-identical to Python):
//   [event: <name>\n]   — only when eventName is truthy
//   [id: <eventId>\n]   — only when eventId is truthy
//   data: <JSON>\n
//   \n
//
// Event types:
//   Normal stream event  — no eventName, id = Redis stream ID
//   Keepalive            — eventName='keepalive', data={"type":"keepalive"}
//   Terminal             — eventName='stream-end',  data={"status":"complete"}
//   Stream error         — eventName='error',        data={"error":"<msg>"}
//   Stream unavailable   — eventName='error',        data={"error":"Stream not available"}

import type { Redis } from 'ioredis'

import {
    KEEPALIVE_INTERVAL_MS,
    SSE_EVENT_ERROR,
    SSE_EVENT_KEEPALIVE,
    SSE_EVENT_STREAM_END,
    SSE_PAYLOAD_KEEPALIVE,
    SSE_PAYLOAD_STREAM_END,
    WAIT_DELAY_INCREMENT_MS,
    WAIT_INITIAL_DELAY_MS,
    WAIT_MAX_DELAY_MS,
    WAIT_TIMEOUT_MS,
    makeSseErrorPayload,
} from '../lib/constants.js'
import { logger } from '../lib/logging.js'
import { TaskRunRedisStream } from '../lib/redis-stream.js'
import type { StreamConnectionOutcome } from '../lib/types.js'
import { TaskRunStreamError } from '../lib/types.js'
import {
    observeStreamConnectionClosed,
    observeStreamConnectionOpened,
    observeStreamLengthOnConnect,
    observeStreamResumeGap,
} from './metrics.js'

// ---------------------------------------------------------------------------
// SSE framing
// ---------------------------------------------------------------------------

/**
 * Format one SSE event frame, byte-identical to the Python format_sse_event.
 *
 * Order: [event: <name>\n] [id: <id>\n] data: <json>\n\n
 *
 * The result is encoded as UTF-8 and returned as a Buffer so callers can pipe
 * it directly into an HTTP response body without additional conversion.
 */
export function formatSseEvent(data: Record<string, unknown>, opts?: { eventId?: string; eventName?: string }): Buffer {
    const parts: string[] = []
    if (opts?.eventName) {
        parts.push(`event: ${opts.eventName}`)
    }
    if (opts?.eventId) {
        parts.push(`id: ${opts.eventId}`)
    }
    parts.push(`data: ${JSON.stringify(data)}`)
    return Buffer.from(parts.join('\n') + '\n\n', 'utf8')
}

// ---------------------------------------------------------------------------
// SSE stream generator
// ---------------------------------------------------------------------------

/**
 * Async generator that yields SSE-formatted byte chunks for one task-run
 * stream connection.
 *
 * Mirrors Python stream_task_run_events exactly:
 *   1. Records opened metric; sets default outcome = 'client_disconnect'.
 *   2. Wait-for-stream loop: polls exists() with linear backoff until the
 *      stream appears or the 120s timeout fires (yields unavailable error event
 *      and returns on timeout; yields keepalive every 20s while waiting).
 *   3. Resolves startId from lastEventId / startLatest / '0'.
 *   4. On reconnect (lastEventId set): observes stream length and checks for
 *      resume gap (best-effort — catches all exceptions, never breaks stream).
 *   5. Iterates readStreamEntries:
 *      - null  → yield keepalive
 *      - entry → yield formatSseEvent(event, {eventId})
 *   6. After generator returns (completion sentinel consumed): yield stream-end
 *      terminal event; set outcome = 'completed'.
 *   7. On TaskRunStreamError: yield error event; set outcome = 'stream_error'.
 *   8. Finally: record closed metric with outcome and duration.
 *
 * @yields {Buffer} SSE-formatted byte chunk (UTF-8 encoded).
 */
export async function* streamTaskRunEvents(
    streamKey: string,
    redis: Redis,
    opts: {
        originProduct?: string
        lastEventId?: string | null
        startLatest?: boolean
    }
): AsyncGenerator<Buffer, void, unknown> {
    const originProduct = opts.originProduct ?? 'unknown'
    const lastEventId = opts.lastEventId ?? null
    const startLatest = opts.startLatest ?? false

    const redisStream = new TaskRunRedisStream(streamKey, redis)
    const connectionStartedAt = Date.now()

    let outcome: StreamConnectionOutcome = 'client_disconnect'
    let opened = false
    // Dedicated blocking-read connection created just before the main read loop.
    // Declared here so the finally block can close it regardless of how the
    // generator exits (completion, error, or client disconnect).
    let dedupRedis: Redis | undefined

    try {
        observeStreamConnectionOpened(originProduct)
        opened = true

        // -- Wait-for-stream loop --
        let delay = WAIT_INITIAL_DELAY_MS
        const waitStartedAt = Date.now()
        let lastKeepaliveAt = waitStartedAt
        let waitedForStream = false
        while (!(await redisStream.exists())) {
            const now = Date.now()

            if (!waitedForStream) {
                waitedForStream = true
                logger.debug('stream:waiting', { streamKey })
            }

            if (now - waitStartedAt >= WAIT_TIMEOUT_MS) {
                outcome = 'unavailable'
                logger.warn('stream:unavailable', { streamKey, waitedMs: now - waitStartedAt })
                yield formatSseEvent(makeSseErrorPayload('Stream not available'), {
                    eventName: SSE_EVENT_ERROR,
                })
                return
            }

            if (now - lastKeepaliveAt >= KEEPALIVE_INTERVAL_MS) {
                lastKeepaliveAt = now
                yield formatSseEvent(SSE_PAYLOAD_KEEPALIVE, { eventName: SSE_EVENT_KEEPALIVE })
            }

            await sleep(delay)
            delay = Math.min(delay + WAIT_DELAY_INCREMENT_MS, WAIT_MAX_DELAY_MS)
        }

        if (waitedForStream) {
            logger.debug('stream:available', { streamKey, waitedMs: Date.now() - waitStartedAt })
        }

        // -- Resolve start ID --
        let startId: string
        if (lastEventId) {
            startId = lastEventId
        } else if (startLatest && !waitedForStream) {
            startId = (await redisStream.getLatestStreamId()) ?? '0'
        } else {
            startId = '0'
        }

        // -- Resume gap detection (only on reconnects; best-effort) --
        if (lastEventId) {
            try {
                observeStreamLengthOnConnect(await redisStream.getLength())
                if (await redisStream.resumePointTrimmed(lastEventId)) {
                    observeStreamResumeGap(originProduct)
                    logger.warn('stream:resume_gap', { streamKey, lastEventId })
                }
            } catch {
                logger.warn('stream:attach_observe_failed', { streamKey })
            }
        }

        // Dedicated connection for the blocking XREAD loop so it cannot delay the
        // shared client's ingest writes (XADD, WATCH/MULTI) or non-blocking reads.
        // Connection count is bounded upstream by StreamCapacity (app.ts), which caps
        // concurrent streams per pod and per run before this duplicate is created.
        // FOLLOWUP: if pod-level connection count becomes a concern within those caps,
        // replace the per-stream duplicate with a small bounded pool of blocking-read
        // connections shared across streams. Not worth the complexity until profiling
        // shows a connection-count problem.
        // enableOfflineQueue:false + lazyConnect means we must call connect() explicitly
        // before the first command and register an error listener.
        dedupRedis = redis.duplicate()
        dedupRedis.on('error', (err: Error) => logger.warn('stream:redis_dup_error', { streamKey, error: err.message }))
        try {
            await dedupRedis.connect()
        } catch (err) {
            // The dedicated connection could not be established (e.g. Redis at its
            // connection limit). Degrade like a mid-stream connection loss: surface
            // an SSE error event rather than throwing a raw error out of the handler.
            outcome = 'stream_error'
            logger.error('stream:redis_dup_connect_failed', {
                streamKey,
                error: err instanceof Error ? err.message : String(err),
            })
            yield formatSseEvent(makeSseErrorPayload('Connection lost to task run stream'), {
                eventName: SSE_EVENT_ERROR,
            })
            return
        }

        // -- Main read loop --
        try {
            for await (const streamItem of redisStream.readStreamEntries({
                startId,
                keepaliveIntervalMs: KEEPALIVE_INTERVAL_MS,
                blockingRedis: dedupRedis,
            })) {
                if (streamItem === null) {
                    // Idle keepalive signal from readStreamEntries
                    yield formatSseEvent(SSE_PAYLOAD_KEEPALIVE, { eventName: SSE_EVENT_KEEPALIVE })
                    continue
                }

                const [eventId, event] = streamItem
                yield formatSseEvent(event, { eventId })
            }

            // Generator returned normally — completion sentinel was consumed.
            outcome = 'completed'
            yield formatSseEvent(SSE_PAYLOAD_STREAM_END, { eventName: SSE_EVENT_STREAM_END })
        } catch (err) {
            if (err instanceof TaskRunStreamError) {
                outcome = 'stream_error'
                logger.error('stream:error', { streamKey, error: err.message })
                yield formatSseEvent(makeSseErrorPayload(err.message), { eventName: SSE_EVENT_ERROR })
            } else {
                throw err
            }
        }
    } finally {
        if (opened) {
            const durationSeconds = (Date.now() - connectionStartedAt) / 1000
            observeStreamConnectionClosed(originProduct, outcome, durationSeconds)
        }
        // Close the dedicated blocking-read connection. ioredis v4 disconnect() is
        // synchronous (returns void) and also aborts any in-flight XREAD BLOCK on
        // client disconnect, which is what we want.
        try {
            dedupRedis?.disconnect()
        } catch {
            // best-effort cleanup — never let teardown throw out of the finally
        }
    }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}
