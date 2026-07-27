// Redis stream read/write plane for task-run event streaming.
//
// Wire protocol is byte-identical to the Python implementation in
// products/tasks/backend/stream/redis_stream.py — Django and this Node
// service share the SAME Redis stream during the cutover window.
// Any change to key names, TTLs, field names, or sentinel shapes will
// corrupt live runs.

import type { Redis } from 'ioredis'

import {
    BLOCK_MS,
    READ_COUNT,
    SEQUENCE_TTL_SECONDS,
    STREAM_MAX_LENGTH,
    STREAM_PREFIX,
    STREAM_TTL_SECONDS,
    WAIT_DELAY_INCREMENT_MS,
    WAIT_INITIAL_DELAY_MS,
    WAIT_MAX_DELAY_MS,
    WAIT_TIMEOUT_MS,
} from './constants.js'
import type { ReadStreamEntriesOptions, ResumeGap, StreamEntryOrKeepalive } from './types.js'
import {
    TaskRunStreamAlreadyCompleted,
    TaskRunStreamCompletionSequenceMismatch,
    TaskRunStreamError,
    TaskRunStreamSequenceGap,
} from './types.js'

// ---------------------------------------------------------------------------
// Key helpers — byte-identical to Python get_task_run_stream_*_key
// ---------------------------------------------------------------------------

export function getStreamKey(runId: string): string {
    return `${STREAM_PREFIX}${runId}`
}

export function getSequenceKey(streamKey: string): string {
    return `${streamKey}:last-seq`
}

export function getCompletedKey(streamKey: string): string {
    return `${streamKey}:completed`
}

export function getAgentActiveKey(streamKey: string): string {
    return `${streamKey}:ingest-agent-active`
}

export function getHeartbeatKey(streamKey: string): string {
    return `${streamKey}:ingest-heartbeat`
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function normalizeStreamId(id: unknown): string {
    if (typeof id === 'string') {
        return id
    }
    if (Buffer.isBuffer(id)) {
        return id.toString('utf8')
    }
    return String(id)
}

function normalizeRedisInt(value: string | Buffer | null | undefined): number {
    if (value == null) {
        return 0
    }
    const str = Buffer.isBuffer(value) ? value.toString('utf8') : String(value)
    const n = parseInt(str, 10)
    return Number.isNaN(n) ? 0 : n
}

// Parse a Redis stream ID "<ms>-<seq>" into a comparable [ms, seq] tuple.
// On any parse failure returns [0, 0] (matches Python _stream_id_sort_key).
function streamIdSortKey(id: string): [number, number] {
    const dashIndex = id.indexOf('-')
    if (dashIndex === -1) {
        const ms = parseInt(id, 10)
        return Number.isNaN(ms) ? [0, 0] : [ms, 0]
    }
    const msPart = id.slice(0, dashIndex)
    const seqPart = id.slice(dashIndex + 1)
    const ms = parseInt(msPart, 10)
    const seq = seqPart === '' ? 0 : parseInt(seqPart, 10)
    if (Number.isNaN(ms) || Number.isNaN(seq)) {
        return [0, 0]
    }
    return [ms, seq]
}

function streamIdLessThan(a: string, b: string): boolean {
    const [aMs, aSeq] = streamIdSortKey(a)
    const [bMs, bSeq] = streamIdSortKey(b)
    return aMs < bMs || (aMs === bMs && aSeq < bSeq)
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

// ---------------------------------------------------------------------------
// TaskRunRedisStream
// ---------------------------------------------------------------------------

// Maximum number of WATCH/MULTI retry iterations before giving up.
// Python's while True retries indefinitely, but unbounded loops are
// unsafe in Node. 100 iterations is far beyond what real contention
// requires — if a slot is genuinely that contested something is wrong.
const MAX_WATCH_RETRIES = 100

export class TaskRunRedisStream {
    private readonly streamKey: string
    private readonly redis: Redis
    private readonly timeout: number
    private readonly sequenceTimeout: number
    private readonly maxLength: number

    constructor(
        streamKey: string,
        redis: Redis,
        opts?: {
            timeout?: number
            maxLength?: number
        }
    ) {
        this.streamKey = streamKey
        this.redis = redis
        this.timeout = opts?.timeout ?? STREAM_TTL_SECONDS
        // sequence key TTL must be at least timeout + SEQUENCE_TTL_SECONDS
        this.sequenceTimeout = Math.max(this.timeout, SEQUENCE_TTL_SECONDS)
        this.maxLength = opts?.maxLength ?? STREAM_MAX_LENGTH
    }

    // SET EXPIRE on the stream key; does not create it.
    async initialize(): Promise<void> {
        await this.redis.expire(this.streamKey, this.timeout)
    }

    // EXISTS stream_key -> bool
    async exists(): Promise<boolean> {
        const count = await this.redis.exists(this.streamKey)
        return count > 0
    }

    // Linear backoff poll: initial 50ms, +150ms/step, cap 2000ms, timeout 120s.
    // Returns true if stream exists, false on timeout.
    async waitForStream(): Promise<boolean> {
        let delay = WAIT_INITIAL_DELAY_MS
        const start = Date.now()

        while (true) {
            const elapsed = Date.now() - start
            if (elapsed >= WAIT_TIMEOUT_MS) {
                return false
            }

            if (await this.exists()) {
                return true
            }

            await sleep(delay)
            delay = Math.min(delay + WAIT_DELAY_INCREMENT_MS, WAIT_MAX_DELAY_MS)
        }
    }

    // XREVRANGE stream_key + - COUNT 1 -> string | null
    async getLatestStreamId(): Promise<string | null> {
        const messages = await this.redis.xrevrange(this.streamKey, '+', '-', 'COUNT', 1)
        if (!messages || messages.length === 0) {
            return null
        }
        const [streamId] = messages[0]
        return normalizeStreamId(streamId)
    }

    // XRANGE stream_key - + COUNT 1 -> string | null
    async getFirstStreamId(): Promise<string | null> {
        const messages = await this.redis.xrange(this.streamKey, '-', '+', 'COUNT', 1)
        if (!messages || messages.length === 0) {
            return null
        }
        const [streamId] = messages[0]
        return normalizeStreamId(streamId)
    }

    // XLEN -> number
    async getLength(): Promise<number> {
        return this.redis.xlen(this.streamKey)
    }

    // False if lastEventId in ('', '0'). False if stream empty.
    // True if streamIdSortKey(lastEventId) < streamIdSortKey(firstId).
    async resumePointTrimmed(lastEventId: string): Promise<boolean> {
        if (lastEventId === '' || lastEventId === '0') {
            return false
        }
        const firstId = await this.getFirstStreamId()
        if (firstId === null) {
            return false
        }
        return streamIdLessThan(lastEventId, firstId)
    }

    // None for startId in ('0','0-0','$',''). None if stream empty.
    // ResumeGap if startId < firstId.
    async detectResumeGap(startId: string): Promise<ResumeGap | null> {
        if (startId === '0' || startId === '0-0' || startId === '$' || startId === '') {
            return null
        }
        const firstId = await this.getFirstStreamId()
        if (firstId === null) {
            return null
        }
        if (streamIdLessThan(startId, firstId)) {
            return { requestedId: startId, oldestAvailableId: firstId }
        }
        return null
    }

    // Async generator: yields [streamId, data] tuples or null (keepalive signal).
    //
    // Advances currentId per entry. XREAD block=100ms count=16.
    // On STREAM_STATUS complete: return (generator ends, sentinel not yielded).
    // On STREAM_STATUS error: throw TaskRunStreamError.
    // On idle >= keepaliveIntervalMs: yield null and reset idle timer.
    // On elapsed > timeout: throw TaskRunStreamError('Stream timeout...').
    // Redis errors mapped to TaskRunStreamError substrings matching Python.
    async *readStreamEntries(opts: ReadStreamEntriesOptions = {}): AsyncGenerator<StreamEntryOrKeepalive> {
        const startId = opts.startId ?? '0'
        const blockMs = opts.blockMs ?? BLOCK_MS
        const count = opts.count ?? READ_COUNT
        const keepaliveIntervalMs = opts.keepaliveIntervalMs ?? null
        // Use a dedicated connection for blocking reads when the caller provides
        // one, so that XREAD BLOCK calls don't queue behind ingest XADD writes
        // on the shared client.
        const xreadClient = opts.blockingRedis ?? this.redis

        let currentId = startId
        const startTime = Date.now()
        let lastYieldTime = startTime

        while (true) {
            const now = Date.now()
            if (now - startTime > this.timeout * 1000) {
                throw new TaskRunStreamError('Stream timeout — task run took too long')
            }

            let messages: Array<[string, Array<[string, string[]]>]> | null = null
            try {
                // ioredis XREAD returns: Array<[streamName, Array<[id, fields]>]>
                // fields is a flat array: [key1, val1, key2, val2, ...]
                const raw = await xreadClient.xread(
                    'COUNT',
                    count,
                    'BLOCK',
                    blockMs,
                    'STREAMS',
                    this.streamKey,
                    currentId
                )
                messages = raw as typeof messages
            } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : String(err)
                if (
                    msg.includes('ECONNREFUSED') ||
                    msg.includes('ECONNRESET') ||
                    msg.includes('Connection is closed')
                ) {
                    throw new TaskRunStreamError('Connection lost to task run stream')
                }
                if (msg.includes('ETIMEDOUT') || msg.includes('timed out')) {
                    throw new TaskRunStreamError('Stream read timeout')
                }
                throw new TaskRunStreamError('Stream read error')
            }

            // TypeScript 6 incorrectly narrows `messages` to `never` inside an
            // async generator when the catch block always throws — false positive.
            // eslint-disable-next-line @typescript-eslint/ban-ts-comment
            // @ts-expect-error TS6 async-generator narrowing false positive
            if (!messages || messages.length === 0) {
                const idleMs = Date.now() - lastYieldTime
                if (keepaliveIntervalMs !== null && idleMs >= keepaliveIntervalMs) {
                    lastYieldTime = Date.now()
                    yield null
                }
                continue
            }

            // @ts-expect-error TS6 async-generator narrowing false positive
            for (const [, streamMessages] of messages) {
                for (const [streamId, fields] of streamMessages) {
                    const normalizedId = normalizeStreamId(streamId)
                    currentId = normalizedId

                    // fields is a flat array [key1, val1, key2, val2, ...]
                    // Find the 'data' field value.
                    let rawData = ''
                    for (let i = 0; i < fields.length - 1; i += 2) {
                        if (fields[i] === 'data') {
                            rawData = fields[i + 1] ?? ''
                            break
                        }
                    }

                    let data: Record<string, unknown>
                    try {
                        data = JSON.parse(rawData) as Record<string, unknown>
                    } catch {
                        // Skip unparseable entries rather than crashing the stream.
                        continue
                    }

                    if (data['type'] === 'STREAM_STATUS') {
                        const status = data['status']
                        if (status === 'complete') {
                            return
                        } else if (status === 'error') {
                            throw new TaskRunStreamError(
                                typeof data['error'] === 'string' ? data['error'] : 'Unknown stream error'
                            )
                        }
                    } else {
                        lastYieldTime = Date.now()
                        yield [normalizedId, data]
                    }
                }
            }
        }
    }

    // XADD + EXPIRE; no sequence check. Returns Redis stream ID string.
    // Refreshes TTL on every write (sliding window).
    async writeEvent(event: Record<string, unknown>): Promise<string> {
        const raw = JSON.stringify(event)
        const streamId = await this.redis.xadd(this.streamKey, 'MAXLEN', '~', this.maxLength, '*', 'data', raw)
        await this.redis.expire(this.streamKey, this.timeout)
        return normalizeStreamId(streamId)
    }

    // GET last-seq; if result is not null EXPIRE it (sliding TTL). Returns int (0 if absent).
    async getLastSequence(): Promise<number> {
        const sequenceKey = getSequenceKey(this.streamKey)
        const raw = await this.redis.get(sequenceKey)
        if (raw !== null) {
            await this.redis.expire(sequenceKey, this.sequenceTimeout)
        }
        return normalizeRedisInt(raw)
    }

    // SET agent-active-key ('1'|'0') EX STREAM_TTL_SECONDS
    async setAgentActive(active: boolean): Promise<void> {
        await this.redis.set(getAgentActiveKey(this.streamKey), active ? '1' : '0', 'EX', this.timeout)
    }

    // GET agent-active-key; true iff value === '1'
    async getAgentActive(): Promise<boolean> {
        const raw = await this.redis.get(getAgentActiveKey(this.streamKey))
        return raw === '1'
    }

    // EXISTS completed-key -> bool
    async isComplete(): Promise<boolean> {
        return (await this.redis.exists(getCompletedKey(this.streamKey))) > 0
    }

    // SET heartbeat-key '1' EX throttleSeconds NX. True if claimed.
    async claimAgentActiveHeartbeat(throttleSeconds: number): Promise<boolean> {
        const result = await this.redis.set(getHeartbeatKey(this.streamKey), '1', 'EX', throttleSeconds, 'NX')
        return result === 'OK'
    }

    // WATCH/MULTI optimistic retry loop (never the TEST shortcut).
    // Returns stream ID string on accept, null on duplicate.
    // Throws TaskRunStreamSequenceGap, TaskRunStreamAlreadyCompleted.
    //
    // Sequences start at 1; sequence 0 is the initial sentinel treated as accepted.
    //   seq == last+1 -> accept (XADD, set last-seq, refresh TTLs, return stream ID)
    //   seq <= last   -> duplicate (return null)
    //   seq > last+1  -> TaskRunStreamSequenceGap
    //   completed key present -> TaskRunStreamAlreadyCompleted
    async writeEventWithSequence(event: Record<string, unknown>, sequence: number): Promise<string | null> {
        const sequenceKey = getSequenceKey(this.streamKey)
        const completedKey = getCompletedKey(this.streamKey)
        const raw = JSON.stringify(event)

        for (let attempt = 0; attempt < MAX_WATCH_RETRIES; attempt++) {
            await this.redis.watch(sequenceKey, completedKey)

            const lastSeqRaw = await this.redis.get(sequenceKey)
            const lastSequence = normalizeRedisInt(lastSeqRaw)
            const completedExists = (await this.redis.exists(completedKey)) > 0

            if (completedExists) {
                await this.redis.unwatch()
                throw new TaskRunStreamAlreadyCompleted(lastSequence)
            }

            if (sequence <= lastSequence) {
                await this.redis.unwatch()
                return null
            }

            if (sequence !== lastSequence + 1) {
                await this.redis.unwatch()
                throw new TaskRunStreamSequenceGap(lastSequence + 1, sequence, lastSequence)
            }

            const pipeline = this.redis.multi()
            pipeline.xadd(this.streamKey, 'MAXLEN', '~', this.maxLength, '*', 'data', raw)
            pipeline.expire(this.streamKey, this.timeout)
            pipeline.set(sequenceKey, String(sequence), 'EX', this.sequenceTimeout)

            const results = await pipeline.exec()
            if (results === null) {
                // WATCH conflict — retry
                continue
            }

            // results[0] is [error, streamId]
            const [xaddErr, streamId] = results[0] ?? [null, null]
            if (xaddErr) {
                throw new TaskRunStreamError(`XADD failed: ${String(xaddErr)}`)
            }
            return normalizeStreamId(streamId)
        }

        throw new TaskRunStreamError('writeEventWithSequence: too many WATCH conflicts')
    }

    // WATCH/MULTI on completed_key. Idempotent: returns if already completed.
    async markComplete(): Promise<void> {
        const completedKey = getCompletedKey(this.streamKey)
        const raw = JSON.stringify({ type: 'STREAM_STATUS', status: 'complete' })

        for (let attempt = 0; attempt < MAX_WATCH_RETRIES; attempt++) {
            await this.redis.watch(completedKey)

            const completedExists = (await this.redis.exists(completedKey)) > 0
            if (completedExists) {
                await this.redis.unwatch()
                return
            }

            const pipeline = this.redis.multi()
            pipeline.xadd(this.streamKey, 'MAXLEN', '~', this.maxLength, '*', 'data', raw)
            pipeline.expire(this.streamKey, this.timeout)
            pipeline.set(completedKey, '1', 'EX', this.sequenceTimeout)

            const results = await pipeline.exec()
            if (results === null) {
                // WATCH conflict — retry
                continue
            }
            return
        }

        throw new TaskRunStreamError('markComplete: too many WATCH conflicts')
    }

    // WATCH/MULTI on sequence_key + completed_key.
    // Throws TaskRunStreamCompletionSequenceMismatch if last_seq != finalSequence.
    // EXPIRE sequence_key only if it existed before (lastSeqRaw !== null).
    async markCompleteAfterSequence(finalSequence: number): Promise<void> {
        const sequenceKey = getSequenceKey(this.streamKey)
        const completedKey = getCompletedKey(this.streamKey)
        const raw = JSON.stringify({ type: 'STREAM_STATUS', status: 'complete' })

        for (let attempt = 0; attempt < MAX_WATCH_RETRIES; attempt++) {
            await this.redis.watch(sequenceKey, completedKey)

            const lastSeqRaw = await this.redis.get(sequenceKey)
            const lastSequence = normalizeRedisInt(lastSeqRaw)
            const completedExists = (await this.redis.exists(completedKey)) > 0

            if (completedExists) {
                await this.redis.unwatch()
                return
            }

            if (lastSequence !== finalSequence) {
                await this.redis.unwatch()
                throw new TaskRunStreamCompletionSequenceMismatch(finalSequence, lastSequence)
            }

            const seqKeyExisted = lastSeqRaw !== null

            const pipeline = this.redis.multi()
            pipeline.xadd(this.streamKey, 'MAXLEN', '~', this.maxLength, '*', 'data', raw)
            pipeline.expire(this.streamKey, this.timeout)
            // Only EXPIRE the sequence key if it existed before the transaction;
            // matches Python: `if last_sequence_raw is not None: pipe.expire(sequence_key, ...)`
            if (seqKeyExisted) {
                pipeline.expire(sequenceKey, this.sequenceTimeout)
            }
            pipeline.set(completedKey, '1', 'EX', this.sequenceTimeout)

            const results = await pipeline.exec()
            if (results === null) {
                // WATCH conflict — retry
                continue
            }
            return
        }

        throw new TaskRunStreamError('markCompleteAfterSequence: too many WATCH conflicts')
    }

    // No WATCH/MULTI. XADD error sentinel, truncated to 500 chars.
    async markError(error: string): Promise<void> {
        await this.writeEvent({ type: 'STREAM_STATUS', status: 'error', error: error.slice(0, 500) })
    }

    // DEL all five keys atomically. Returns true if at least one key was deleted.
    // Catches all exceptions; returns false on failure.
    async deleteStream(): Promise<boolean> {
        try {
            const sequenceKey = getSequenceKey(this.streamKey)
            const completedKey = getCompletedKey(this.streamKey)
            const agentActiveKey = getAgentActiveKey(this.streamKey)
            const heartbeatKey = getHeartbeatKey(this.streamKey)
            const deleted = await this.redis.del(
                this.streamKey,
                sequenceKey,
                completedKey,
                agentActiveKey,
                heartbeatKey
            )
            return deleted > 0
        } catch {
            return false
        }
    }
}
