// NDJSON event ingest handler for POST /v1/runs/:run/ingest
//
// Wire protocol stays byte-identical to event_ingest.py — both the Python and
// Node services read/write the same Redis stream during the cutover window.
//
// HTTP status codes:
//   200  success: {accepted, duplicate, last_accepted_seq}
//   400  bad NDJSON: invalid JSON, non-object, wrong field types, ordering
//   401  missing / invalid JWT
//   403  JWT claims don't match URL params
//   405  wrong HTTP method
//   408  client disconnected mid-body: {error, last_accepted_seq}
//   409  SequenceGap / AlreadyCompleted / CompletionSequenceMismatch: {error, last_accepted_seq}
//   413  payload too large: {error, last_accepted_seq}

import type { CryptoKey } from 'crypto'
import type { Context } from 'hono'
import type { Redis } from 'ioredis'

import type { Config } from '../lib/config.js'
import {
    MAX_EVENT_LINE_BYTES,
    MAX_REQUEST_BYTES,
    MAX_EVENTS_PER_REQUEST,
    STREAM_COMPLETE_CONTROL_TYPE,
} from '../lib/constants.js'
import { validateSandboxEventIngestToken } from '../lib/jwt.js'
import { logger } from '../lib/logging.js'
import { TaskRunRedisStream, getStreamKey } from '../lib/redis-stream.js'
import { heartbeatWorkflowIfNeeded } from '../lib/side-effects.js'
import {
    ClientDisconnected,
    EventIngestBadRequest,
    EventIngestPayloadTooLarge,
    TaskRunStreamSequenceGap,
    TaskRunStreamAlreadyCompleted,
    TaskRunStreamCompletionSequenceMismatch,
    type IngestEventLine,
    type IngestCompleteLine,
    type IngestLine,
    type EventIngestResult,
    type SandboxEventIngestTokenPayload,
} from '../lib/types.js'
import { observeStreamIngestEvents } from './metrics.js'

// Diagnostic (temporary): records when request-body chunks arrive at the Node
// process, to tell a live upload (chunks spread across the request lifetime)
// from a body buffered upstream and delivered in one burst at request close.
// The sandbox holds one long-lived chunked POST open for the whole turn; if
// chunks only land when that request closes, the stall is upstream of this
// process. Remove once the buffering hop is pinned down.
interface IngestBodyTiming {
    startedAt: number
    firstChunkAt: number | null
    lastChunkAt: number | null
    chunks: number
    bytes: number
}

// ---------------------------------------------------------------------------
// Route handler (exported; wired in app.ts)
// ---------------------------------------------------------------------------

export async function handleIngest(
    c: Context,
    redis: Redis,
    config: Config,
    publicKeys: CryptoKey[]
): Promise<Response> {
    // Method guard (Hono enforces the route method, but keep an explicit check
    // so the handler is safe when registered on a catch-all route too).
    if (c.req.method !== 'POST') {
        return c.json({ error: 'Method not allowed' }, 405)
    }

    // Authorization: Bearer <token> only (no ?token= fallback on ingest).
    const token = extractBearerToken(c)
    if (token === null) {
        return c.json({ error: 'Missing authorization bearer token' }, 401)
    }

    // JWT validation.
    let claims: SandboxEventIngestTokenPayload
    try {
        claims = await validateSandboxEventIngestToken(token, publicKeys)
    } catch (err: unknown) {
        const code = err instanceof Error ? err.constructor.name : 'UnknownError'
        return c.json({ error: 'Invalid event ingest token', code }, 401)
    }

    // The run-scoped JWT is the authority (Django minted it for this run/task/team);
    // the run path segment only has to agree with the token's run claim. team/task
    // come from the verified token, not the URL.
    const { run } = c.req.param() as { run: string }
    if (claims.runId !== run) {
        return c.json({ error: 'Token does not match run' }, 403)
    }

    // No run-existence check. The run-scoped sandbox_event_ingest JWT is the
    // authorization — Django minted it for this exact run/task/team. Keeping the
    // ingest plane free of a per-request Django round-trip is the whole point of
    // the standalone proxy; events for a run deleted mid-stream land in the TTL-
    // and MAXLEN-bounded Redis stream and are never read.

    // NDJSON body parsing + Redis writes.
    const streamKey = getStreamKey(claims.runId)
    const redisStream = new TaskRunRedisStream(streamKey, redis)

    const bodyTiming: IngestBodyTiming = {
        startedAt: Date.now(),
        firstChunkAt: null,
        lastChunkAt: null,
        chunks: 0,
        bytes: 0,
    }

    let result: EventIngestResult
    try {
        result = await ingestEventLines(redisStream, claims, token, config, c.req.raw, bodyTiming)
    } catch (err: unknown) {
        if (err instanceof ClientDisconnected) {
            logger.info('ingest:client_disconnect', {
                run: claims.runId,
                accepted: err.accepted,
                duplicate: err.duplicate,
                lastSeq: err.lastAcceptedSeq,
                chunks: bodyTiming.chunks,
                bodyBytes: bodyTiming.bytes,
            })
            return c.json({ error: 'Client disconnected', last_accepted_seq: err.lastAcceptedSeq }, 408)
        }
        if (err instanceof EventIngestBadRequest) {
            return c.json({ error: err.message }, 400)
        }
        if (err instanceof EventIngestPayloadTooLarge) {
            return c.json({ error: err.message, last_accepted_seq: err.lastAcceptedSeq }, 413)
        }
        if (err instanceof TaskRunStreamSequenceGap) {
            return c.json({ error: err.message, last_accepted_seq: err.lastAcceptedSeq }, 409)
        }
        if (err instanceof TaskRunStreamAlreadyCompleted) {
            return c.json({ error: err.message, last_accepted_seq: err.lastAcceptedSeq }, 409)
        }
        if (err instanceof TaskRunStreamCompletionSequenceMismatch) {
            return c.json({ error: err.message, last_accepted_seq: err.lastAcceptedSeq }, 409)
        }
        throw err
    }

    observeStreamIngestEvents({ accepted: result.accepted, duplicate: result.duplicate })

    logger.info('ingest', {
        run: claims.runId,
        accepted: result.accepted,
        duplicate: result.duplicate,
        lastSeq: result.last_accepted_seq,
        // Body-arrival timing. Live upload: firstChunkMs small, chunkSpanMs
        // large. Buffered upstream: firstChunkMs ~= lastChunkMs, chunkSpanMs ~0
        // (every chunk lands together when the request closes).
        chunks: bodyTiming.chunks,
        bodyBytes: bodyTiming.bytes,
        firstChunkMs: bodyTiming.firstChunkAt === null ? null : bodyTiming.firstChunkAt - bodyTiming.startedAt,
        lastChunkMs: bodyTiming.lastChunkAt === null ? null : bodyTiming.lastChunkAt - bodyTiming.startedAt,
        chunkSpanMs:
            bodyTiming.firstChunkAt === null || bodyTiming.lastChunkAt === null
                ? null
                : bodyTiming.lastChunkAt - bodyTiming.firstChunkAt,
    })

    return c.json(
        {
            accepted: result.accepted,
            duplicate: result.duplicate,
            last_accepted_seq: result.last_accepted_seq,
        },
        200
    )
}

// ---------------------------------------------------------------------------
// NDJSON body parsing + Redis write loop
// ---------------------------------------------------------------------------

async function ingestEventLines(
    redisStream: TaskRunRedisStream,
    claims: SandboxEventIngestTokenPayload,
    originalToken: string,
    config: Config,
    rawRequest: Request,
    bodyTiming: IngestBodyTiming
): Promise<EventIngestResult> {
    const result: EventIngestResult = {
        accepted: 0,
        duplicate: 0,
        last_accepted_seq: await redisStream.getLastSequence(),
    }

    let eventCount = 0
    let completionLineFinalSeq: number | null = null

    try {
        for await (const line of iterRequestLines(rawRequest, claims.runId, bodyTiming)) {
            const parsed = parseIngestLine(line)

            if (parsed.kind === 'complete') {
                if (completionLineFinalSeq !== null) {
                    throw new EventIngestBadRequest('Completion line must be the final event stream line')
                }
                completionLineFinalSeq = (parsed as IngestCompleteLine).finalSeq
                continue
            }

            if (completionLineFinalSeq !== null) {
                throw new EventIngestBadRequest('Completion line must be the final event stream line')
            }

            const eventLine = parsed as IngestEventLine
            eventCount++
            if (eventCount > MAX_EVENTS_PER_REQUEST) {
                throw new EventIngestPayloadTooLarge('Too many events in request', result.last_accepted_seq)
            }

            const { seq, event } = eventLine
            const streamId = await redisStream.writeEventWithSequence(event, seq)

            if (streamId === null) {
                // Duplicate: advance last_accepted_seq to whatever Redis has.
                result.duplicate++
                result.last_accepted_seq = Math.max(result.last_accepted_seq, await redisStream.getLastSequence())
                continue
            }

            result.accepted++
            result.last_accepted_seq = seq

            await heartbeatWorkflowIfNeeded(
                redisStream,
                claims.runId,
                event,
                claims.taskId,
                claims.teamId,
                originalToken,
                config
            )
        }
    } catch (err: unknown) {
        if (err instanceof ClientDisconnected) {
            err.accepted = result.accepted
            err.duplicate = result.duplicate
            err.lastAcceptedSeq = result.last_accepted_seq
        }
        // Re-throw EventIngestPayloadTooLarge with the current last_accepted_seq
        // if the error didn't carry one (mirrors Python's except re-raise).
        if (err instanceof EventIngestPayloadTooLarge && result.last_accepted_seq > 0 && err.lastAcceptedSeq === 0) {
            err.lastAcceptedSeq = result.last_accepted_seq
        }
        throw err
    }

    if (completionLineFinalSeq !== null) {
        await redisStream.markCompleteAfterSequence(completionLineFinalSeq)
    }

    return result
}

// ---------------------------------------------------------------------------
// NDJSON line parser (mirrors _parse_ingest_line)
// ---------------------------------------------------------------------------

function parseIngestLine(line: string): IngestLine {
    let payload: unknown
    try {
        payload = JSON.parse(line)
    } catch {
        throw new EventIngestBadRequest('Invalid JSON line')
    }

    if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) {
        throw new EventIngestBadRequest('Each event line must be a JSON object')
    }

    const obj = payload as Record<string, unknown>

    // Completion line detection (must come before event line parsing).
    if (obj['type'] === STREAM_COMPLETE_CONTROL_TYPE) {
        const finalSeq = obj['final_seq']
        // type(final_sequence) is not int or final_sequence < 0 (Python exact check).
        // typeof guards booleans (typeof true === 'boolean', not 'number').
        if (typeof finalSeq !== 'number' || !Number.isInteger(finalSeq) || finalSeq < 0) {
            throw new EventIngestBadRequest('Completion final sequence must be a non-negative integer')
        }
        return { kind: 'complete', finalSeq }
    }

    // Event line.
    const seq = obj['seq']
    const event = obj['event']

    // typeof guards booleans (typeof true === 'boolean', not 'number').
    if (typeof seq !== 'number' || !Number.isInteger(seq) || seq < 1) {
        throw new EventIngestBadRequest('Event sequence must be a positive integer')
    }
    if (typeof event !== 'object' || event === null || Array.isArray(event)) {
        throw new EventIngestBadRequest('Event payload must be an object')
    }

    return { kind: 'event', seq, event: event as Record<string, unknown> }
}

// ---------------------------------------------------------------------------
// Streaming NDJSON body reader (mirrors _iter_request_lines)
// ---------------------------------------------------------------------------

async function* iterRequestLines(request: Request, run: string, timing: IngestBodyTiming): AsyncGenerator<string> {
    const body = request.body
    if (body === null) {
        return
    }

    const reader = body.getReader()
    let buffer = new Uint8Array(0)
    let requestSize = 0
    const newline = 0x0a // '\n'

    try {
        while (true) {
            const { done, value } = await reader.read().catch((err: unknown) => {
                throw isClientAbortError(err) ? new ClientDisconnected() : err
            })

            if (value !== undefined && value.length > 0) {
                const chunkAt = Date.now()
                if (timing.firstChunkAt === null) {
                    timing.firstChunkAt = chunkAt
                }
                timing.lastChunkAt = chunkAt
                timing.chunks += 1
                timing.bytes += value.length
                logger.debug('ingest:body_chunk', {
                    run,
                    chunk: timing.chunks,
                    bytes: value.length,
                    sinceStartMs: chunkAt - timing.startedAt,
                })

                requestSize += value.length
                if (requestSize > MAX_REQUEST_BYTES) {
                    throw new EventIngestPayloadTooLarge('Event ingest request is too large')
                }

                // Append chunk to buffer.
                const combined = new Uint8Array(buffer.length + value.length)
                combined.set(buffer)
                combined.set(value, buffer.length)
                buffer = combined

                // Guard: if the buffer is larger than one max line with no newline,
                // the line itself is already too large.
                if (buffer.length > MAX_EVENT_LINE_BYTES && !buffer.includes(newline)) {
                    throw new EventIngestPayloadTooLarge('Event line is too large')
                }

                // Yield all complete lines (terminated by '\n').
                let start = 0
                for (let i = 0; i < buffer.length; i++) {
                    if (buffer[i] === newline) {
                        const lineBytes = buffer.subarray(start, i)
                        start = i + 1

                        if (lineBytes.length > MAX_EVENT_LINE_BYTES) {
                            throw new EventIngestPayloadTooLarge('Event line is too large')
                        }

                        // Trim whitespace (strip).
                        const trimmed = trimBytes(lineBytes)
                        if (trimmed.length === 0) {
                            continue
                        }

                        yield decodeUtf8(trimmed)
                    }
                }

                // Keep the partial trailing line in buffer.
                buffer = buffer.subarray(start)
            }

            if (done) {
                // Flush trailing partial line.
                const trimmed = trimBytes(buffer)
                if (trimmed.length > 0) {
                    if (trimmed.length > MAX_EVENT_LINE_BYTES) {
                        throw new EventIngestPayloadTooLarge('Event line is too large')
                    }
                    yield decodeUtf8(trimmed)
                }
                return
            }
        }
    } finally {
        reader.releaseLock()
    }
}

function isClientAbortError(err: unknown): boolean {
    if (!(err instanceof Error)) {
        return false
    }
    if (err.name === 'AbortError') {
        return true
    }
    const code = (err as NodeJS.ErrnoException).code
    return code === 'ECONNRESET' || code === 'ERR_STREAM_PREMATURE_CLOSE' || err.message === 'aborted'
}

// Decode bytes as UTF-8, mapping decode errors to EventIngestBadRequest.
function decodeUtf8(bytes: Uint8Array): string {
    try {
        // TextDecoder with fatal:true throws on invalid byte sequences.
        return new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    } catch {
        throw new EventIngestBadRequest('Invalid UTF-8 in event stream')
    }
}

// Trim leading and trailing ASCII whitespace bytes (space, tab, CR, LF).
function trimBytes(bytes: Uint8Array): Uint8Array {
    const isWs = (b: number): boolean => b === 0x20 || b === 0x09 || b === 0x0d || b === 0x0a
    let start = 0
    let end = bytes.length
    while (start < end && isWs(bytes[start] ?? 0)) {
        start++
    }
    while (end > start && isWs(bytes[end - 1] ?? 0)) {
        end--
    }
    return bytes.subarray(start, end)
}

// ---------------------------------------------------------------------------
// Token extraction
// ---------------------------------------------------------------------------

function extractBearerToken(c: Context): string | null {
    const authorization = c.req.header('Authorization') ?? c.req.header('authorization')
    if (!authorization) {
        return null
    }
    const prefix = 'Bearer '
    if (!authorization.startsWith(prefix)) {
        return null
    }
    const token = authorization.slice(prefix.length).trim()
    return token || null
}
