// Tests for SSE framing and streamTaskRunEvents generator.
//
// Wire-protocol invariant: SSE output must be byte-identical to the Python
// format_sse_event in products/tasks/backend/stream/sse.py. Django and this
// Node service read/write the SAME Redis stream during the cutover window.
//
// Coverage mirrors products/tasks/backend/stream/tests/test_sse.py plus the
// timing paths (keepalive cadence, wait-for-stream timeout) that are hard to
// exercise in Python without mocking.

import type { Redis } from 'ioredis'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { formatSseEvent, streamTaskRunEvents } from '@/hono/sse-handler.js'
import {
    KEEPALIVE_INTERVAL_MS,
    SSE_EVENT_ERROR,
    SSE_EVENT_KEEPALIVE,
    SSE_EVENT_STREAM_END,
    WAIT_TIMEOUT_MS,
} from '@/lib/constants.js'

// ---------------------------------------------------------------------------
// Minimal in-memory fake Redis
//
// Implements exactly the subset of the ioredis API that TaskRunRedisStream
// uses.  The goal is correctness of the SSE framing and generator flow, not
// exhaustive Redis semantics.
// ---------------------------------------------------------------------------

interface StreamMessage {
    id: string
    fields: Record<string, string>
}

let _autoSeq = 0
function nextStreamId(): string {
    _autoSeq++
    return `${Date.now()}-${_autoSeq}`
}

class FakeRedisPipeline {
    private readonly ops: Array<() => [null, unknown]> = []
    private readonly store: FakeRedis

    constructor(store: FakeRedis) {
        this.store = store
    }

    xadd(key: string, ...args: string[]): this {
        this.ops.push(() => {
            const id = this.store._xadd(key, args)
            return [null, id]
        })
        return this
    }

    expire(_key: string, _seconds: number): this {
        this.ops.push(() => [null, 1])
        return this
    }

    set(key: string, value: string, ..._rest: string[]): this {
        this.ops.push(() => {
            this.store._set(key, value)
            return [null, 'OK']
        })
        return this
    }

    async exec(): Promise<Array<[null, unknown]> | null> {
        if (this.store._watchConflict) {
            this.store._watchConflict = false
            return null
        }
        const results: Array<[null, unknown]> = []
        for (const op of this.ops) {
            results.push(op())
        }
        return results
    }
}

// Shape that ioredis XREAD returns:
//   Array<[streamName, Array<[id, fields_flat_array]>]>
type XreadResult = Array<[string, Array<[string, string[]]>]>

class FakeRedis {
    private readonly strings = new Map<string, string>()
    private readonly streams = new Map<string, StreamMessage[]>()

    // Set this true before the next pipeline exec() to simulate a WATCH conflict.
    _watchConflict = false

    // Blocked XREAD calls waiting for new messages.
    private pendingReads: Array<{
        streamKey: string
        currentId: string
        resolve: (result: XreadResult | null) => void
    }> = []

    // ---------------------------------------------------------------------------
    // Helpers used by FakeRedisPipeline
    // ---------------------------------------------------------------------------

    _xadd(key: string, args: string[]): string {
        // args: ['MAXLEN', '~', maxlen, '*', 'data', value]  or bare ['*', 'data', value]
        const idIdx = args.indexOf('*')
        const id = nextStreamId()
        const fieldsFlat = args.slice(idIdx + 1)
        const fields: Record<string, string> = {}
        for (let i = 0; i < fieldsFlat.length - 1; i += 2) {
            fields[fieldsFlat[i] as string] = fieldsFlat[i + 1] as string
        }
        const msg: StreamMessage = { id, fields }
        const bucket = this.streams.get(key) ?? []
        bucket.push(msg)
        this.streams.set(key, bucket)

        // Notify any blocked XREAD waiting on this key.
        const pending = this.pendingReads.filter((r) => r.streamKey === key)
        for (const waiter of pending) {
            this.pendingReads = this.pendingReads.filter((r) => r !== waiter)
            const matching = bucket.filter((m) => this._streamIdGt(m.id, waiter.currentId))
            if (matching.length > 0) {
                waiter.resolve([[key, matching.map((m) => [m.id, this._flatFields(m.fields)])]])
            } else {
                waiter.resolve(null)
            }
        }

        return id
    }

    _set(key: string, value: string): void {
        this.strings.set(key, value)
    }

    // ---------------------------------------------------------------------------
    // ioredis-compatible API surface
    // ---------------------------------------------------------------------------

    async exists(key: string): Promise<number> {
        const hasStr = this.strings.has(key)
        const hasStream = (this.streams.get(key)?.length ?? 0) > 0
        return hasStr || hasStream ? 1 : 0
    }

    async get(key: string): Promise<string | null> {
        return this.strings.get(key) ?? null
    }

    async set(key: string, value: string, ..._rest: unknown[]): Promise<string> {
        this.strings.set(key, value)
        return 'OK'
    }

    async expire(_key: string, _seconds: number): Promise<number> {
        return 1
    }

    async del(...keys: string[]): Promise<number> {
        let n = 0
        for (const k of keys) {
            if (this.strings.delete(k) || this.streams.delete(k)) {
                n++
            }
        }
        return n
    }

    async xadd(key: string, ...args: string[]): Promise<string> {
        return this._xadd(key, args)
    }

    async xlen(key: string): Promise<number> {
        return this.streams.get(key)?.length ?? 0
    }

    async xrange(key: string, start: string, end: string, ..._rest: unknown[]): Promise<Array<[string, string[]]>> {
        const msgs = this.streams.get(key) ?? []
        return msgs.filter((m) => this._inRange(m.id, start, end)).map((m) => [m.id, this._flatFields(m.fields)])
    }

    async xrevrange(key: string, end: string, start: string, ..._rest: unknown[]): Promise<Array<[string, string[]]>> {
        const msgs = (this.streams.get(key) ?? []).slice()
        return msgs
            .reverse()
            .filter((m) => this._inRange(m.id, start, end))
            .map((m) => [m.id, this._flatFields(m.fields)])
    }

    // XREAD COUNT count BLOCK blockMs STREAMS key currentId
    async xread(...args: unknown[]): Promise<XreadResult | null> {
        const argsStr = args.map(String)
        const streamsIdx = argsStr.indexOf('STREAMS')
        const streamKey = argsStr[streamsIdx + 1] as string
        const currentId = argsStr[streamsIdx + 2] as string
        const blockIdx = argsStr.indexOf('BLOCK')
        const blockMs = blockIdx === -1 ? 0 : parseInt(argsStr[blockIdx + 1] as string, 10)
        const countIdx = argsStr.indexOf('COUNT')
        const count = countIdx === -1 ? 16 : parseInt(argsStr[countIdx + 1] as string, 10)

        const bucket = this.streams.get(streamKey) ?? []
        const matching = bucket.filter((m) => this._streamIdGt(m.id, currentId)).slice(0, count)

        if (matching.length > 0) {
            return [[streamKey, matching.map((m) => [m.id, this._flatFields(m.fields)])]]
        }

        if (blockMs === 0) {
            return null
        }

        // Blocking read: return a promise that resolves when new data arrives
        // or the block timeout fires.
        return new Promise<XreadResult | null>((resolve) => {
            const entry = { streamKey, currentId, resolve }
            this.pendingReads.push(entry)

            // Resolve with null after blockMs (simulates XREAD block timeout).
            // We use the real setTimeout here; in fake-timer tests the test
            // controls when time advances, so the timeout fires on demand.
            setTimeout(() => {
                this.pendingReads = this.pendingReads.filter((r) => r !== entry)
                resolve(null)
            }, blockMs)
        })
    }

    async watch(..._keys: string[]): Promise<string> {
        return 'OK'
    }

    async unwatch(): Promise<string> {
        return 'OK'
    }

    multi(): FakeRedisPipeline {
        return new FakeRedisPipeline(this)
    }

    // Stubs for the per-stream redis.duplicate() connection lifecycle.
    // duplicate() returns `this` so the shared in-memory store is visible to
    // both the "shared" and "blocking" sides — correct for single-threaded tests.
    duplicate(): this {
        return this
    }

    async connect(): Promise<void> {}

    async disconnect(): Promise<void> {}

    on(_event: string, _handler: (...args: unknown[]) => void): this {
        return this
    }

    // ---------------------------------------------------------------------------
    // Internal helpers
    // ---------------------------------------------------------------------------

    private _flatFields(fields: Record<string, string>): string[] {
        const flat: string[] = []
        for (const [k, v] of Object.entries(fields)) {
            flat.push(k, v)
        }
        return flat
    }

    private _parseId(id: string): [number, number] {
        if (id === '-') {
            return [0, 0]
        }
        if (id === '+') {
            return [Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER]
        }
        if (id === '0' || id === '0-0') {
            return [0, 0]
        }
        const dash = id.indexOf('-')
        if (dash === -1) {
            return [parseInt(id, 10) || 0, 0]
        }
        return [parseInt(id.slice(0, dash), 10) || 0, parseInt(id.slice(dash + 1), 10) || 0]
    }

    private _streamIdGt(id: string, cursor: string): boolean {
        const [aMs, aSeq] = this._parseId(id)
        const [bMs, bSeq] = this._parseId(cursor)
        return aMs > bMs || (aMs === bMs && aSeq > bSeq)
    }

    private _inRange(id: string, start: string, end: string): boolean {
        const [ms, seq] = this._parseId(id)
        const [startMs, startSeq] = this._parseId(start)
        const [endMs, endSeq] = this._parseId(end)
        const afterStart = ms > startMs || (ms === startMs && seq >= startSeq)
        const beforeEnd = ms < endMs || (ms === endMs && seq <= endSeq)
        return afterStart && beforeEnd
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function collect(gen: AsyncGenerator<Buffer, void, unknown>): Promise<string> {
    const chunks: string[] = []
    for await (const chunk of gen) {
        chunks.push(chunk.toString('utf8'))
    }
    return chunks.join('')
}

function makeStreamKey(runId: string): string {
    return `task-run-stream:${runId}`
}

function uniqueRunId(): string {
    return `test-run-${crypto.randomUUID()}`
}

// Write a data entry directly to the fake stream (bypasses sequence checks).
function xaddData(redis: FakeRedis, streamKey: string, event: Record<string, unknown>): void {
    void redis.xadd(streamKey, 'MAXLEN', '~', '20000', '*', 'data', JSON.stringify(event))
}

// Write the completion sentinel.
function xaddComplete(redis: FakeRedis, streamKey: string): void {
    xaddData(redis, streamKey, { type: 'STREAM_STATUS', status: 'complete' })
}

// Write the error sentinel.
function xaddError(redis: FakeRedis, streamKey: string, error: string): void {
    xaddData(redis, streamKey, { type: 'STREAM_STATUS', status: 'error', error })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('sse-handler', () => {
    let redis: FakeRedis

    beforeEach(() => {
        redis = new FakeRedis()
        _autoSeq = 0
        vi.restoreAllMocks()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    // -------------------------------------------------------------------------
    // formatSseEvent — wire-protocol byte framing
    // -------------------------------------------------------------------------

    describe('formatSseEvent', () => {
        it('emits data line terminated by a double newline for a plain event', () => {
            const buf = formatSseEvent({ hello: 'world' })
            const text = buf.toString('utf8')
            expect(text).toBe('data: {"hello":"world"}\n\n')
        })

        it('emits event line before id and data when eventName is given', () => {
            const buf = formatSseEvent({ type: 'keepalive' }, { eventName: 'keepalive' })
            const text = buf.toString('utf8')
            expect(text).toBe('event: keepalive\ndata: {"type":"keepalive"}\n\n')
        })

        it('emits id line between event and data when eventId is given', () => {
            const buf = formatSseEvent({ msg: 'hi' }, { eventId: '123-1', eventName: 'message' })
            const text = buf.toString('utf8')
            expect(text).toBe('event: message\nid: 123-1\ndata: {"msg":"hi"}\n\n')
        })

        it('emits only id and data when eventName is omitted', () => {
            const buf = formatSseEvent({ seq: 1 }, { eventId: '456-0' })
            const text = buf.toString('utf8')
            expect(text).toBe('id: 456-0\ndata: {"seq":1}\n\n')
        })

        it('returns a Buffer', () => {
            const buf = formatSseEvent({ x: 1 })
            expect(Buffer.isBuffer(buf)).toBe(true)
        })

        it('always ends with exactly two newlines (blank line delimiter)', () => {
            // 4 opts × 2 expects each; oxlint's static analyser does not descend into for-loops
            expect.assertions(8)
            for (const opts of [{}, { eventName: 'ping' }, { eventId: '1-0' }, { eventName: 'ping', eventId: '1-0' }]) {
                const text = formatSseEvent({ n: 1 }, opts).toString('utf8')
                expect(text.endsWith('\n\n')).toBe(true)
                // No triple newline — only one blank line.
                expect(text.includes('\n\n\n')).toBe(false)
            }
        })

        it('does not emit event line when eventName is empty string', () => {
            const text = formatSseEvent({ x: 1 }, { eventName: '' }).toString('utf8')
            expect(text.startsWith('event:')).toBe(false)
        })

        it('does not emit id line when eventId is empty string', () => {
            const text = formatSseEvent({ x: 1 }, { eventId: '' }).toString('utf8')
            expect(text.includes('id:')).toBe(false)
        })
    })

    // -------------------------------------------------------------------------
    // streamTaskRunEvents — normal stream events then stream-end terminal
    // -------------------------------------------------------------------------

    describe('streamTaskRunEvents — happy path', () => {
        it('emits events then stream-end terminal on clean completion', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddData(redis, streamKey, { type: 'notification', msg: 'hello' })
            xaddComplete(redis, streamKey)

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            expect(body).toContain('"msg":"hello"')
            expect(body).toContain(`event: ${SSE_EVENT_STREAM_END}`)
            expect(body).toContain('"status":"complete"')
        })

        it('emits normal events without an event: line (only id: and data:)', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddData(redis, streamKey, { type: 'notification', msg: 'test' })
            xaddComplete(redis, streamKey)

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            // Split into individual SSE frames (blank-line delimited).
            const frames = body.split('\n\n').filter((f) => f.trim() !== '')

            // First frame is the data event — must not have an event: line.
            const dataFrame = frames.find((f) => f.includes('"msg":"test"'))
            expect(dataFrame).toBeTruthy()
            expect(dataFrame!.startsWith('event:')).toBe(false)

            // It must carry an id: line (the Redis stream ID).
            expect(dataFrame!).toContain('id:')
        })

        it('does not yield the completion sentinel as a data event', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddComplete(redis, streamKey)

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            // The STREAM_STATUS sentinel must never appear as a data payload.
            expect(body).not.toContain('"STREAM_STATUS"')
            expect(body).not.toContain('"status":"complete"' + '\n\n')
            // The terminal stream-end event carries status:complete in a named event frame.
            expect(body).toContain(`event: ${SSE_EVENT_STREAM_END}`)
        })

        it('emits multiple events in order before stream-end', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddData(redis, streamKey, { type: 'notification', msg: 'first' })
            xaddData(redis, streamKey, { type: 'notification', msg: 'second' })
            xaddData(redis, streamKey, { type: 'notification', msg: 'third' })
            xaddComplete(redis, streamKey)

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            const firstPos = body.indexOf('"first"')
            const secondPos = body.indexOf('"second"')
            const thirdPos = body.indexOf('"third"')
            const endPos = body.indexOf(SSE_EVENT_STREAM_END)

            expect(firstPos).toBeLessThan(secondPos)
            expect(secondPos).toBeLessThan(thirdPos)
            expect(thirdPos).toBeLessThan(endPos)
        })
    })

    // -------------------------------------------------------------------------
    // streamTaskRunEvents — terminal stream-end event framing
    // -------------------------------------------------------------------------

    describe('streamTaskRunEvents — terminal stream-end event', () => {
        it('terminal event is named stream-end and carries {status:complete}', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddComplete(redis, streamKey)

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            // Find the stream-end frame.
            const frames = body.split('\n\n').filter((f) => f.trim() !== '')
            const terminalFrame = frames.find((f) => f.includes(SSE_EVENT_STREAM_END))
            expect(terminalFrame).toBeTruthy()
            expect(terminalFrame!).toBe(`event: ${SSE_EVENT_STREAM_END}\ndata: {"status":"complete"}`)
        })
    })

    // -------------------------------------------------------------------------
    // streamTaskRunEvents — error sentinel
    // -------------------------------------------------------------------------

    describe('streamTaskRunEvents — stream error event', () => {
        it('emits error event and stops on error sentinel', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddData(redis, streamKey, { type: 'notification', msg: 'before error' })
            xaddError(redis, streamKey, 'boom')

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            expect(body).toContain('"before error"')
            expect(body).toContain(`event: ${SSE_EVENT_ERROR}`)
            expect(body).toContain('"boom"')
        })

        it('does not emit stream-end after an error', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddError(redis, streamKey, 'catastrophic failure')

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            expect(body).not.toContain(SSE_EVENT_STREAM_END)
        })

        it('error event is named error and carries {error:"..."} payload', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddError(redis, streamKey, 'disk full')

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            const frames = body.split('\n\n').filter((f) => f.trim() !== '')
            const errorFrame = frames.find((f) => f.includes(`event: ${SSE_EVENT_ERROR}`))
            expect(errorFrame).toBeTruthy()
            expect(errorFrame!).toContain('"disk full"')
        })
    })

    // -------------------------------------------------------------------------
    // streamTaskRunEvents — resume from Last-Event-ID
    // -------------------------------------------------------------------------

    describe('streamTaskRunEvents — resume from Last-Event-ID', () => {
        it('resumes from last-event-id, skipping events already seen', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddData(redis, streamKey, { type: 'notification', msg: 'first' })
            // Capture the id of the first event to use as Last-Event-ID.
            const msgs = await redis.xrange(streamKey, '-', '+', 'COUNT', 1)
            const firstId = msgs[0]![0]

            xaddData(redis, streamKey, { type: 'notification', msg: 'second' })
            xaddComplete(redis, streamKey)

            const body = await collect(
                streamTaskRunEvents(streamKey, redis as unknown as Redis, { lastEventId: firstId })
            )

            expect(body).toContain('"second"')
            expect(body).not.toContain('"first"')
            expect(body).toContain(SSE_EVENT_STREAM_END)
        })

        it('id field in each SSE frame matches the Redis stream ID used for resuming', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddData(redis, streamKey, { type: 'notification', msg: 'ping' })
            xaddComplete(redis, streamKey)

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            // The data frame must contain an "id:" line.
            const frames = body.split('\n\n').filter((f) => f.trim() !== '')
            const dataFrame = frames.find((f) => f.includes('"ping"'))
            expect(dataFrame).toBeTruthy()
            const idLine = dataFrame!.split('\n').find((l) => l.startsWith('id:'))
            expect(idLine).toBeTruthy()

            // The id value must look like a Redis stream ID ("<ms>-<seq>").
            const idValue = idLine!.slice('id: '.length)
            expect(idValue).toMatch(/^\d+-\d+$/)
        })
    })

    // -------------------------------------------------------------------------
    // streamTaskRunEvents — startLatest
    // -------------------------------------------------------------------------

    describe('streamTaskRunEvents — startLatest', () => {
        it('with startLatest=true skips already-written events and reads only new ones', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddData(redis, streamKey, { type: 'notification', msg: 'old' })

            // Stream the generator; because startLatest=true it reads from the
            // latest ID.  We must add the completion sentinel after the generator
            // starts waiting so that it sees it.  Use a short async delay.
            const genPromise = (async () => {
                const chunks: string[] = []
                const gen = streamTaskRunEvents(streamKey, redis as unknown as Redis, { startLatest: true })
                for await (const chunk of gen) {
                    chunks.push(chunk.toString('utf8'))
                }
                return chunks.join('')
            })()

            // Let the generator start its XREAD wait, then push new data and complete.
            await new Promise((r) => setTimeout(r, 50))
            xaddData(redis, streamKey, { type: 'notification', msg: 'new' })
            xaddComplete(redis, streamKey)

            const body = await genPromise

            expect(body).not.toContain('"old"')
            expect(body).toContain('"new"')
            expect(body).toContain(SSE_EVENT_STREAM_END)
        })

        it('with startLatest=true reads from the beginning when the stream appears after connect', async () => {
            vi.useFakeTimers()

            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            const bodyPromise = collect(
                streamTaskRunEvents(streamKey, redis as unknown as Redis, { startLatest: true })
            )

            await Promise.resolve()
            await Promise.resolve()
            xaddData(redis, streamKey, { type: 'notification', msg: 'first-after-wait' })
            xaddComplete(redis, streamKey)
            await vi.advanceTimersByTimeAsync(100)

            const body = await bodyPromise

            expect(body).toContain('"first-after-wait"')
            expect(body).toContain(SSE_EVENT_STREAM_END)
        })
    })

    // -------------------------------------------------------------------------
    // streamTaskRunEvents — keepalive emission
    // -------------------------------------------------------------------------

    describe('streamTaskRunEvents — keepalive emission', () => {
        it('emits a keepalive SSE event named keepalive with {type:keepalive} payload', async () => {
            vi.useFakeTimers()

            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            // Stream is available immediately but has no events yet.
            xaddData(redis, streamKey, { type: 'PLACEHOLDER' })

            let resolveKeepalive!: (buf: Buffer) => void
            const keepaliveSeen = new Promise<Buffer>((r) => {
                resolveKeepalive = r
            })

            const gen = streamTaskRunEvents(streamKey, redis as unknown as Redis, {})

            // Collect chunks in the background, resolving on the first keepalive frame.
            const collecting = (async () => {
                for await (const chunk of gen) {
                    if (chunk.toString('utf8').includes(`event: ${SSE_EVENT_KEEPALIVE}`)) {
                        resolveKeepalive(chunk)
                        break
                    }
                }
            })()

            // Advance time past the keepalive threshold to trigger it.
            await vi.advanceTimersByTimeAsync(KEEPALIVE_INTERVAL_MS + 500)
            xaddComplete(redis, streamKey)

            const kaBuf = await keepaliveSeen
            const kaText = kaBuf.toString('utf8')
            expect(kaText).toContain(`event: ${SSE_EVENT_KEEPALIVE}`)
            expect(kaText).toContain('"type":"keepalive"')

            await collecting
        })
    })

    // -------------------------------------------------------------------------
    // streamTaskRunEvents — wait-for-stream timeout
    // -------------------------------------------------------------------------

    describe('streamTaskRunEvents — wait-for-stream timeout', () => {
        it('emits error event with "Stream not available" when stream never appears', async () => {
            vi.useFakeTimers()

            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)
            // Do NOT add any entries — stream does not exist.

            const bodyPromise = collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            // Advance past the 120 s wait timeout.
            await vi.advanceTimersByTimeAsync(WAIT_TIMEOUT_MS + 1_000)

            const body = await bodyPromise

            expect(body).toContain(`event: ${SSE_EVENT_ERROR}`)
            expect(body).toContain('Stream not available')
        })

        it('emits keepalive events while waiting for the stream to appear', async () => {
            vi.useFakeTimers()

            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            const chunks: string[] = []
            const gen = streamTaskRunEvents(streamKey, redis as unknown as Redis, {})

            const collecting = (async () => {
                for await (const chunk of gen) {
                    chunks.push(chunk.toString('utf8'))
                }
            })()

            // Advance time by enough to trigger one keepalive during the wait.
            await vi.advanceTimersByTimeAsync(KEEPALIVE_INTERVAL_MS + 500)

            // Now make the stream appear and complete it so the generator can finish.
            xaddComplete(redis, streamKey)
            await vi.advanceTimersByTimeAsync(2_000)

            await collecting

            const body = chunks.join('')
            expect(body).toContain(`event: ${SSE_EVENT_KEEPALIVE}`)
        })
    })

    // -------------------------------------------------------------------------
    // streamTaskRunEvents — SSE framing invariants over full output
    // -------------------------------------------------------------------------

    describe('streamTaskRunEvents — framing invariants', () => {
        it('every SSE frame ends with exactly one blank line', async () => {
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddData(redis, streamKey, { type: 'notification', msg: 'a' })
            xaddData(redis, streamKey, { type: 'notification', msg: 'b' })
            xaddComplete(redis, streamKey)

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            // No triple newline (i.e. no empty frame or double blank line).
            expect(body).not.toContain('\n\n\n')
            // Body ends with exactly \n\n.
            expect(body.endsWith('\n\n')).toBe(true)
        })

        it('each data event frame has exactly one data: line', async () => {
            // Assertions are inside a for-loop; oxlint's static analyser does not descend into them
            expect.hasAssertions()
            const runId = uniqueRunId()
            const streamKey = makeStreamKey(runId)

            xaddData(redis, streamKey, { type: 'notification', msg: 'single' })
            xaddComplete(redis, streamKey)

            const body = await collect(streamTaskRunEvents(streamKey, redis as unknown as Redis, {}))

            const frames = body.split('\n\n').filter((f) => f.trim() !== '')
            for (const frame of frames) {
                const dataLines = frame.split('\n').filter((l) => l.startsWith('data:'))
                expect(dataLines.length).toBe(1)
            }
        })
    })
})
