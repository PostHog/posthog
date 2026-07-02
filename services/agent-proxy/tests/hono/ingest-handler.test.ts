// Tests for ingest-handler.ts
//
// Coverage goals (mirrors products/tasks/backend/stream/tests/):
//   - NDJSON parsing across chunk boundaries
//   - Byte/line/count limits → 413 with last_accepted_seq
//   - Sequence gap + already-completed → 409
//   - Accepted/duplicate counting + last_accepted_seq tracking
//   - Completion line handling (happy path, mismatch, ordering errors)
//   - Side-effect triggering: turn-complete vs session/update vs throttled heartbeat
//   - Best-effort side effects: callback failure does not fail ingest
//
// Wire-protocol invariants tested:
//   - Stream key: "task-run-stream:{run_id}"
//   - Sequence numbers start at 1 (0 is the initial sentinel)
//   - Completion sentinel: {"type":"STREAM_STATUS","status":"complete"}
//   - Redis field name is "data"

import type { Redis } from 'ioredis'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import type { Config } from '@/lib/config.js'
import {
    MAX_EVENT_LINE_BYTES,
    MAX_REQUEST_BYTES,
    MAX_EVENTS_PER_REQUEST,
    HEARTBEAT_THROTTLE_SECONDS,
} from '@/lib/constants.js'
import { logger } from '@/lib/logging.js'
import { TaskRunRedisStream, getStreamKey } from '@/lib/redis-stream.js'
import { heartbeatWorkflowIfNeeded } from '@/lib/side-effects.js'
import type { SandboxEventIngestTokenPayload } from '@/lib/types.js'

// ---------------------------------------------------------------------------
// Minimal in-memory Redis fake
//
// Implements: get, set, exists, del, expire, xadd, watch, unwatch, multi
// Enough surface for TaskRunRedisStream.writeEventWithSequence,
// getLastSequence, setAgentActive, getAgentActive, claimAgentActiveHeartbeat,
// markCompleteAfterSequence, and deleteStream.
// ---------------------------------------------------------------------------

interface StreamEntry {
    id: string
    data: Record<string, string>
}

class FakeRedis {
    private strings = new Map<string, { value: string; expireAt: number | null }>()
    private streams = new Map<string, StreamEntry[]>()
    private watchedKeys = new Set<string>()
    private watchConflict = false
    private seq = 0

    // Allow tests to simulate a WATCH conflict once.
    simulateWatchConflict(): void {
        this.watchConflict = true
    }

    private nextStreamId(): string {
        this.seq++
        return `${Date.now()}-${this.seq}`
    }

    async get(key: string): Promise<string | null> {
        const entry = this.strings.get(key)
        if (!entry) {
            return null
        }
        if (entry.expireAt !== null && Date.now() > entry.expireAt) {
            this.strings.delete(key)
            return null
        }
        return entry.value
    }

    async set(key: string, value: string, ...args: (string | number)[]): Promise<'OK'> {
        let ttl: number | null = null
        let nx = false
        for (let i = 0; i < args.length; i++) {
            const arg = args[i]
            if (typeof arg === 'string' && arg.toUpperCase() === 'EX') {
                const raw = args[i + 1]
                ttl = typeof raw === 'number' ? raw : parseInt(String(raw), 10)
                i++
            }
            if (typeof arg === 'string' && arg.toUpperCase() === 'NX') {
                nx = true
            }
        }
        if (nx && this.strings.has(key)) {
            const existing = this.strings.get(key)!
            if (existing.expireAt === null || Date.now() <= existing.expireAt) {
                return 'OK' as const // NX: don't overwrite — return 'OK' but value unchanged
                // NOTE: real ioredis returns null on NX fail. We handle this below.
            }
        }
        this.strings.set(key, {
            value,
            expireAt: ttl !== null ? Date.now() + ttl * 1000 : null,
        })
        return 'OK'
    }

    // Real ioredis returns null when SET NX fails. Override for that contract.
    async setNX(key: string, value: string, ttl: number): Promise<string | null> {
        const existing = this.strings.get(key)
        if (existing && (existing.expireAt === null || Date.now() <= existing.expireAt)) {
            return null
        }
        this.strings.set(key, { value, expireAt: Date.now() + ttl * 1000 })
        return 'OK'
    }

    async exists(...keys: string[]): Promise<number> {
        let count = 0
        for (const key of keys) {
            const entry = this.strings.get(key)
            if (entry && (entry.expireAt === null || Date.now() <= entry.expireAt)) {
                count++
            }
        }
        return count
    }

    async expire(key: string, seconds: number): Promise<number> {
        const entry = this.strings.get(key)
        if (entry) {
            entry.expireAt = Date.now() + seconds * 1000
        }
        return entry ? 1 : 0
    }

    async del(...keys: string[]): Promise<number> {
        let deleted = 0
        for (const key of keys) {
            if (this.strings.delete(key)) {
                deleted++
            }
            if (this.streams.delete(key)) {
                deleted++
            }
        }
        return deleted
    }

    async xadd(
        key: string,
        _maxlenToken: 'MAXLEN',
        _approxToken: '~',
        _maxLen: number,
        _idSpec: '*',
        ...fieldValues: string[]
    ): Promise<string> {
        const id = this.nextStreamId()
        const data: Record<string, string> = {}
        for (let i = 0; i + 1 < fieldValues.length; i += 2) {
            data[fieldValues[i]!] = fieldValues[i + 1]!
        }
        const entries = this.streams.get(key) ?? []
        entries.push({ id, data })
        this.streams.set(key, entries)
        return id
    }

    async xrange(key: string, _start = '-', _end = '+'): Promise<[string, Record<string, string>][]> {
        const entries = this.streams.get(key) ?? []
        return entries.map((e) => [e.id, e.data])
    }

    async watch(...keys: string[]): Promise<'OK'> {
        for (const k of keys) {
            this.watchedKeys.add(k)
        }
        return 'OK'
    }

    async unwatch(): Promise<'OK'> {
        this.watchedKeys.clear()
        return 'OK'
    }

    // Returns a fake pipeline (MULTI).
    multi(): FakePipeline {
        const conflict = this.watchConflict
        this.watchConflict = false
        return new FakePipeline(this, conflict)
    }
}

// Rewrite `set` so NX behaviour is correct (returns null not 'OK' on failure).
// We patch FakeRedis.set to correctly handle NX per ioredis contract.
const _origSet = FakeRedis.prototype.set
FakeRedis.prototype.set = async function (
    this: FakeRedis,
    key: string,
    value: string,
    ...args: (string | number)[]
): Promise<'OK' | null> {
    let nx = false
    for (const arg of args) {
        if (typeof arg === 'string' && arg.toUpperCase() === 'NX') {
            nx = true
        }
    }
    if (nx) {
        const existing = await this.get(key)
        if (existing !== null) {
            // NX fail — don't overwrite, return null (ioredis contract)
            return null as unknown as 'OK'
        }
    }
    return _origSet.call(this, key, value, ...args)
} as typeof FakeRedis.prototype.set

class FakePipeline {
    private ops: Array<() => Promise<[null, unknown]>> = []
    private conflictOnExec: boolean

    constructor(
        private redis: FakeRedis,
        conflict: boolean
    ) {
        this.conflictOnExec = conflict
    }

    xadd(
        key: string,
        maxlenToken: 'MAXLEN',
        approxToken: '~',
        maxLen: number,
        idSpec: '*',
        ...fieldValues: string[]
    ): this {
        this.ops.push(async () => {
            const id = await this.redis.xadd(key, maxlenToken, approxToken, maxLen, idSpec, ...fieldValues)
            return [null, id]
        })
        return this
    }

    set(key: string, value: string, ...args: (string | number)[]): this {
        this.ops.push(async () => {
            const result = await this.redis.set(key, value, ...args)
            return [null, result]
        })
        return this
    }

    expire(key: string, seconds: number): this {
        this.ops.push(async () => {
            const result = await this.redis.expire(key, seconds)
            return [null, result]
        })
        return this
    }

    async exec(): Promise<Array<[null, unknown]> | null> {
        if (this.conflictOnExec) {
            return null
        }
        const results: Array<[null, unknown]> = []
        for (const op of this.ops) {
            results.push(await op())
        }
        return results
    }
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeFakeRedis(): FakeRedis {
    return new FakeRedis()
}

function makeRedisStream(fakeRedis: FakeRedis, runId: string): TaskRunRedisStream {
    return new TaskRunRedisStream(getStreamKey(runId), fakeRedis as unknown as Redis, { timeout: 60, maxLength: 20000 })
}

// Build a minimal Config with no Django callback URL so side-effect HTTP calls are skipped.
function makeConfig(overrides?: Partial<Config>): Config {
    return {
        redisUrl: 'redis://localhost:6379',
        sandboxJwtPublicKeysPem: [],
        corsOrigins: new Set(),
        djangoCallbackBaseUrl: '',
        agentProxyCallbackSecret: '',
        maxConcurrentStreams: 1000,
        maxStreamsPerRun: 25,
        metricsToken: '',
        port: 8003,
        host: '0.0.0.0',
        shutdownGraceMs: 300_000,
        shutdownPrestopDelayMs: 0,
        ...overrides,
    }
}

// Build claims for the given runId/taskId/teamId.
function makeClaims(overrides?: Partial<SandboxEventIngestTokenPayload>): SandboxEventIngestTokenPayload {
    return {
        runId: 'run-123',
        taskId: 'task-abc',
        teamId: 42,
        ...overrides,
    }
}

// Build a ReadableStream body from an array of Uint8Array chunks.
function makeChunkedBody(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
    let idx = 0
    return new ReadableStream({
        pull(controller) {
            const chunk = chunks[idx++]
            if (chunk === undefined) {
                controller.close()
                return
            }
            controller.enqueue(chunk)
        },
    })
}

// Build a ReadableStream body from a plain string.
function makeStringBody(text: string): ReadableStream<Uint8Array> {
    const encoded = new TextEncoder().encode(text)
    return makeChunkedBody([encoded])
}

// Import the private helpers by re-exporting a thin shim that calls them.
// Because ingest-handler.ts doesn't export the inner loop helpers, we drive
// the behavior through the exported handleIngest() function with a mocked Hono
// Context, a mocked JWT validator, and a mocked run-exists check.
//
// We avoid unit-testing the private functions directly; instead we observe
// their behavior via the public surface (handleIngest or the sub-module
// heartbeatWorkflowIfNeeded exported from side-effects.ts).

// Inline the re-exported NDJSON + Redis write helpers under test via the
// ingestEventLines path driven through the public handler.
// We wire handleIngest with a fake Hono context and a pre-validated claims object
// (by vi.mocking the JWT module).

vi.mock('@/lib/jwt.js', () => ({
    validateSandboxEventIngestToken: vi.fn(),
    validateStreamReadToken: vi.fn(),
    loadPublicKey: vi.fn(),
}))

import { handleIngest } from '@/hono/ingest-handler.js'
import { validateSandboxEventIngestToken } from '@/lib/jwt.js'

const mockValidate = vi.mocked(validateSandboxEventIngestToken)

// Build a minimal Hono Context-like object sufficient for handleIngest.
function makeContext(opts: {
    runId?: string
    method?: string
    token?: string
    body?: ReadableStream<Uint8Array> | null
}): Parameters<typeof handleIngest>[0] {
    const { runId = 'run-123', method = 'POST', token = 'test-token', body = null } = opts

    return {
        req: {
            method,
            param: () => ({ run: runId }),
            header: (name: string) => {
                const lc = name.toLowerCase()
                if (lc === 'authorization') {
                    return token ? `Bearer ${token}` : undefined
                }
                return undefined
            },
            raw: new Request('http://localhost/', {
                method: 'POST',
                body,
                // Required for streaming body in Node
                // @ts-expect-error duplex is Node-only
                duplex: 'half',
            }),
        },
        json: (data: unknown, status: number) => {
            return new Response(JSON.stringify(data), {
                status,
                headers: { 'Content-Type': 'application/json' },
            })
        },
    } as unknown as Parameters<typeof handleIngest>[0]
}

// Decode a JSON response body.
async function decodeJson(res: Response): Promise<unknown> {
    return res.json()
}

// ---------------------------------------------------------------------------
// Describe block
// ---------------------------------------------------------------------------

describe('ingest-handler', () => {
    let fakeRedis: FakeRedis
    let redisStream: TaskRunRedisStream
    const RUN_ID = 'run-123'
    const TASK_ID = 'task-abc'
    const TEAM_ID = 42

    beforeEach(() => {
        fakeRedis = makeFakeRedis()
        redisStream = makeRedisStream(fakeRedis, RUN_ID)
        vi.clearAllMocks()
        // Default: token is valid, claims match the route params
        mockValidate.mockResolvedValue(makeClaims())
    })

    // -----------------------------------------------------------------------
    // Auth / routing guards
    // -----------------------------------------------------------------------

    it('returns 405 on non-POST', async () => {
        const config = makeConfig()
        const ctx = makeContext({ method: 'GET' })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(405)
    })

    it('returns 401 when Authorization header is missing', async () => {
        const config = makeConfig()
        const ctx = makeContext({ token: '' })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(401)
    })

    it('returns 401 when JWT validation fails', async () => {
        mockValidate.mockRejectedValue(new Error('invalid signature'))
        const config = makeConfig()
        const ctx = makeContext({ body: makeStringBody('') })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(401)
    })

    it('returns 403 when run id in claims does not match route', async () => {
        mockValidate.mockResolvedValue(makeClaims({ runId: 'different-run' }))
        const config = makeConfig()
        const ctx = makeContext({ body: makeStringBody('') })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(403)
    })

    // -----------------------------------------------------------------------
    // Happy-path: single event accepted
    // -----------------------------------------------------------------------

    it('returns 200 with accepted=1 duplicate=0 last_accepted_seq=1 for a single valid event', async () => {
        const config = makeConfig()
        const ndjson = JSON.stringify({ seq: 1, event: { type: 'message' } }) + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)
        const body = await decodeJson(res)
        expect(body).toMatchObject({ accepted: 1, duplicate: 0, last_accepted_seq: 1 })
    })

    it('writes complete NDJSON lines before the request body closes', async () => {
        const config = makeConfig()
        const encoder = new TextEncoder()
        let controller!: ReadableStreamDefaultController<Uint8Array>
        const body = new ReadableStream<Uint8Array>({
            start(c) {
                controller = c
            },
        })

        const resPromise = handleIngest(makeContext({ body }), fakeRedis as unknown as Redis, config, [] as CryptoKey[])

        controller.enqueue(encoder.encode(`${JSON.stringify({ seq: 1, event: { type: 'first-live' } })}\n`))

        await vi.waitFor(async () => {
            const entries = await fakeRedis.xrange(getStreamKey(RUN_ID))
            expect(entries).toHaveLength(1)
            expect(entries[0]?.[1].data).toContain('"first-live"')
        })

        controller.enqueue(encoder.encode(`${JSON.stringify({ seq: 2, event: { type: 'second-live' } })}\n`))
        controller.close()

        const res = await resPromise
        expect(res.status).toBe(200)
        const responseBody = await decodeJson(res)
        expect(responseBody).toMatchObject({ accepted: 2, duplicate: 0, last_accepted_seq: 2 })
    })

    it('accepts multiple sequential events', async () => {
        const config = makeConfig()
        const lines =
            [
                JSON.stringify({ seq: 1, event: { type: 'a' } }),
                JSON.stringify({ seq: 2, event: { type: 'b' } }),
                JSON.stringify({ seq: 3, event: { type: 'c' } }),
            ].join('\n') + '\n'
        const ctx = makeContext({ body: makeStringBody(lines) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)
        const body = (await decodeJson(res)) as { accepted: number; duplicate: number; last_accepted_seq: number }
        expect(body.accepted).toBe(3)
        expect(body.duplicate).toBe(0)
        expect(body.last_accepted_seq).toBe(3)
    })

    // -----------------------------------------------------------------------
    // Duplicate handling
    // -----------------------------------------------------------------------

    it('counts duplicate when same seq sent twice', async () => {
        const config = makeConfig()
        // First request: accept seq 1
        const ndjson1 = JSON.stringify({ seq: 1, event: { type: 'first' } }) + '\n'
        const ctx1 = makeContext({ body: makeStringBody(ndjson1) })
        await handleIngest(ctx1, fakeRedis as unknown as Redis, config, [] as CryptoKey[])

        // Second request: resend seq 1 → duplicate
        const ndjson2 = JSON.stringify({ seq: 1, event: { type: 'first-again' } }) + '\n'
        const ctx2 = makeContext({ body: makeStringBody(ndjson2) })
        const res2 = await handleIngest(ctx2, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res2.status).toBe(200)
        const body = (await decodeJson(res2)) as { accepted: number; duplicate: number; last_accepted_seq: number }
        expect(body.accepted).toBe(0)
        expect(body.duplicate).toBe(1)
        expect(body.last_accepted_seq).toBe(1)
    })

    it('mixes accepted and duplicate when some events are re-sent', async () => {
        const config = makeConfig()
        // Seed seq 1 via a prior request
        const seed = JSON.stringify({ seq: 1, event: { type: 'seed' } }) + '\n'
        await handleIngest(
            makeContext({ body: makeStringBody(seed) }),
            fakeRedis as unknown as Redis,
            config,
            [] as CryptoKey[]
        )

        // Resend seq 1 + new seq 2
        const mixed =
            [
                JSON.stringify({ seq: 1, event: { type: 'duplicate' } }),
                JSON.stringify({ seq: 2, event: { type: 'new' } }),
            ].join('\n') + '\n'
        const res = await handleIngest(
            makeContext({ body: makeStringBody(mixed) }),
            fakeRedis as unknown as Redis,
            config,
            [] as CryptoKey[]
        )
        expect(res.status).toBe(200)
        const body = (await decodeJson(res)) as { accepted: number; duplicate: number; last_accepted_seq: number }
        expect(body.accepted).toBe(1)
        expect(body.duplicate).toBe(1)
        expect(body.last_accepted_seq).toBe(2)
    })

    // -----------------------------------------------------------------------
    // Sequence gap → 409
    // -----------------------------------------------------------------------

    it('returns 409 for a sequence gap with last_accepted_seq', async () => {
        const config = makeConfig()
        // seq 2 without first accepting seq 1
        const ndjson = JSON.stringify({ seq: 2, event: { type: 'jump' } }) + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(409)
        const body = (await decodeJson(res)) as { last_accepted_seq: number }
        expect(body.last_accepted_seq).toBe(0)
    })

    it('reports correct last_accepted_seq in sequence gap response after prior accepts', async () => {
        const config = makeConfig()
        // Accept 1 and 2 first
        const setup =
            [JSON.stringify({ seq: 1, event: { type: 'a' } }), JSON.stringify({ seq: 2, event: { type: 'b' } })].join(
                '\n'
            ) + '\n'
        await handleIngest(
            makeContext({ body: makeStringBody(setup) }),
            fakeRedis as unknown as Redis,
            config,
            [] as CryptoKey[]
        )

        // Now send seq 4 (gap at 3)
        const gap = JSON.stringify({ seq: 4, event: { type: 'skip' } }) + '\n'
        const res = await handleIngest(
            makeContext({ body: makeStringBody(gap) }),
            fakeRedis as unknown as Redis,
            config,
            [] as CryptoKey[]
        )
        expect(res.status).toBe(409)
        const body = (await decodeJson(res)) as { last_accepted_seq: number }
        expect(body.last_accepted_seq).toBe(2)
    })

    // -----------------------------------------------------------------------
    // Already-completed → 409
    // -----------------------------------------------------------------------

    it('returns 409 when writing to an already-completed stream', async () => {
        const config = makeConfig()
        // Accept 1 and mark complete
        const ndjson1 =
            JSON.stringify({ seq: 1, event: { type: 'msg' } }) +
            '\n' +
            JSON.stringify({ type: '_posthog/stream_complete', final_seq: 1 }) +
            '\n'
        await handleIngest(
            makeContext({ body: makeStringBody(ndjson1) }),
            fakeRedis as unknown as Redis,
            config,
            [] as CryptoKey[]
        )

        // Second request: try to write seq 2
        const ndjson2 = JSON.stringify({ seq: 2, event: { type: 'late' } }) + '\n'
        const res = await handleIngest(
            makeContext({ body: makeStringBody(ndjson2) }),
            fakeRedis as unknown as Redis,
            config,
            [] as CryptoKey[]
        )
        expect(res.status).toBe(409)
        const body = (await decodeJson(res)) as { last_accepted_seq: number }
        expect(body.last_accepted_seq).toBe(1)
    })

    // -----------------------------------------------------------------------
    // Completion line: happy path
    // -----------------------------------------------------------------------

    it('accepts completion line with final_seq matching last accepted', async () => {
        const config = makeConfig()
        const ndjson =
            [
                JSON.stringify({ seq: 1, event: { type: 'msg' } }),
                JSON.stringify({ type: '_posthog/stream_complete', final_seq: 1 }),
            ].join('\n') + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)
        const body = (await decodeJson(res)) as { accepted: number; last_accepted_seq: number }
        expect(body.accepted).toBe(1)
        expect(body.last_accepted_seq).toBe(1)

        // Verify the completion sentinel was written to the Redis stream.
        const entries = await fakeRedis.xrange(getStreamKey(RUN_ID))
        const sentinelEntry = entries.find(([, fields]) => {
            const raw = fields['data']
            if (!raw) {
                return false
            }
            const parsed = JSON.parse(raw)
            return parsed.type === 'STREAM_STATUS' && parsed.status === 'complete'
        })
        expect(sentinelEntry).toBeTruthy()
    })

    it('returns 409 when completion final_seq does not match last accepted', async () => {
        const config = makeConfig()
        const ndjson =
            [
                JSON.stringify({ seq: 1, event: { type: 'msg' } }),
                // final_seq=2 but only seq 1 was accepted
                JSON.stringify({ type: '_posthog/stream_complete', final_seq: 2 }),
            ].join('\n') + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(409)
        const body = (await decodeJson(res)) as { last_accepted_seq: number }
        expect(body.last_accepted_seq).toBe(1)
    })

    it('accepts completion line with final_seq=0 when no events were sent', async () => {
        const config = makeConfig()
        const ndjson = JSON.stringify({ type: '_posthog/stream_complete', final_seq: 0 }) + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)
    })

    it('returns 400 when an event line follows the completion line', async () => {
        const config = makeConfig()
        const ndjson =
            [
                JSON.stringify({ type: '_posthog/stream_complete', final_seq: 0 }),
                JSON.stringify({ seq: 1, event: { type: 'after' } }),
            ].join('\n') + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(400)
    })

    it('returns 400 when completion line appears more than once', async () => {
        const config = makeConfig()
        const ndjson =
            [
                JSON.stringify({ type: '_posthog/stream_complete', final_seq: 0 }),
                JSON.stringify({ type: '_posthog/stream_complete', final_seq: 0 }),
            ].join('\n') + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(400)
    })

    // -----------------------------------------------------------------------
    // NDJSON parsing: chunk-boundary splitting
    // -----------------------------------------------------------------------

    it('parses NDJSON correctly when JSON object is split across two chunks', async () => {
        const config = makeConfig()
        const line = JSON.stringify({ seq: 1, event: { type: 'chunked' } })
        const full = line + '\n'
        const mid = Math.floor(full.length / 2)
        const enc = new TextEncoder()
        const chunk1 = enc.encode(full.slice(0, mid))
        const chunk2 = enc.encode(full.slice(mid))
        const body = makeChunkedBody([chunk1, chunk2])
        const ctx = makeContext({ body })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)
        const rb = (await decodeJson(res)) as { accepted: number }
        expect(rb.accepted).toBe(1)
    })

    it('parses multiple events when newlines land at chunk boundaries', async () => {
        const config = makeConfig()
        const enc = new TextEncoder()
        // Build two lines, split so the newline after line 1 is in its own chunk
        const line1 = JSON.stringify({ seq: 1, event: { type: 'a' } })
        const line2 = JSON.stringify({ seq: 2, event: { type: 'b' } })
        const chunks = [enc.encode(line1), enc.encode('\n'), enc.encode(line2), enc.encode('\n')]
        const body = makeChunkedBody(chunks)
        const ctx = makeContext({ body })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)
        const rb = (await decodeJson(res)) as { accepted: number }
        expect(rb.accepted).toBe(2)
    })

    it('handles a trailing partial line with no trailing newline', async () => {
        const config = makeConfig()
        const line = JSON.stringify({ seq: 1, event: { type: 'no-newline' } })
        // No trailing newline — the flush-on-done path handles it
        const ctx = makeContext({ body: makeStringBody(line) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)
        const rb = (await decodeJson(res)) as { accepted: number }
        expect(rb.accepted).toBe(1)
    })

    it('skips blank lines between events', async () => {
        const config = makeConfig()
        const ndjson =
            '\n' +
            JSON.stringify({ seq: 1, event: { type: 'a' } }) +
            '\n\n' +
            JSON.stringify({ seq: 2, event: { type: 'b' } }) +
            '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)
        const rb = (await decodeJson(res)) as { accepted: number }
        expect(rb.accepted).toBe(2)
    })

    // -----------------------------------------------------------------------
    // Byte / line / count limits → 413
    // -----------------------------------------------------------------------

    it('returns 413 when request body exceeds MAX_REQUEST_BYTES', async () => {
        const config = makeConfig()
        const enc = new TextEncoder()

        // Chunk 1: a valid event line that fits within MAX_REQUEST_BYTES.
        // This chunk is processed first; seq 1 is yielded and accepted.
        const line1 = JSON.stringify({ seq: 1, event: { type: 'ok' } }) + '\n'

        // Chunk 2: another event line whose addition pushes the cumulative total
        // over MAX_REQUEST_BYTES, triggering the 413 before seq 2 is accepted.
        // The check is requestSize > MAX_REQUEST_BYTES after adding the chunk,
        // so we need chunk2.length > MAX_REQUEST_BYTES - chunk1.length.
        const padding = 'x'.repeat(MAX_REQUEST_BYTES)
        const line2 = JSON.stringify({ seq: 2, event: { type: 'big', data: padding } }) + '\n'

        const body = makeChunkedBody([enc.encode(line1), enc.encode(line2)])
        const ctx = makeContext({ body })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(413)
        const rb = (await decodeJson(res)) as { last_accepted_seq: number }
        // seq 1 was accepted (chunk 1 was processed) before chunk 2 exceeded the limit
        expect(rb.last_accepted_seq).toBe(1)
    })

    it('returns 413 when a single line exceeds MAX_EVENT_LINE_BYTES', async () => {
        const config = makeConfig()
        // A single event line larger than 1_000_000 bytes.
        const hugePayload = 'y'.repeat(MAX_EVENT_LINE_BYTES + 1)
        const ndjson = JSON.stringify({ seq: 1, event: { data: hugePayload } }) + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(413)
    })

    it('returns 413 when event count exceeds MAX_EVENTS_PER_REQUEST', async () => {
        const config = makeConfig()
        const lines: string[] = []
        for (let i = 1; i <= MAX_EVENTS_PER_REQUEST + 1; i++) {
            lines.push(JSON.stringify({ seq: i, event: { type: 'e' } }))
        }
        const ndjson = lines.join('\n') + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(413)
        const body = (await decodeJson(res)) as { last_accepted_seq: number }
        // last_accepted_seq should be MAX_EVENTS_PER_REQUEST (the last accepted before the limit)
        expect(body.last_accepted_seq).toBe(MAX_EVENTS_PER_REQUEST)
    })

    // -----------------------------------------------------------------------
    // NDJSON parse errors → 400
    // -----------------------------------------------------------------------

    it('returns 400 for invalid JSON', async () => {
        const config = makeConfig()
        const ctx = makeContext({ body: makeStringBody('not json\n') })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(400)
    })

    it('returns 400 for a JSON array (not an object)', async () => {
        const config = makeConfig()
        const ctx = makeContext({ body: makeStringBody('[1,2]\n') })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(400)
    })

    it('returns 400 for seq=0 (must be >= 1)', async () => {
        const config = makeConfig()
        const ctx = makeContext({ body: makeStringBody(JSON.stringify({ seq: 0, event: {} }) + '\n') })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(400)
    })

    it('returns 400 when seq is not an integer', async () => {
        const config = makeConfig()
        const ctx = makeContext({ body: makeStringBody(JSON.stringify({ seq: 1.5, event: {} }) + '\n') })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(400)
    })

    it('returns 400 when event field is not an object', async () => {
        const config = makeConfig()
        const ctx = makeContext({ body: makeStringBody(JSON.stringify({ seq: 1, event: 'string' }) + '\n') })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(400)
    })

    it('returns 400 when completion final_seq is negative', async () => {
        const config = makeConfig()
        const ctx = makeContext({
            body: makeStringBody(JSON.stringify({ type: '_posthog/stream_complete', final_seq: -1 }) + '\n'),
        })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(400)
    })

    it('returns 400 when completion final_seq is not an integer', async () => {
        const config = makeConfig()
        const ctx = makeContext({
            body: makeStringBody(JSON.stringify({ type: '_posthog/stream_complete', final_seq: 1.5 }) + '\n'),
        })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(400)
    })

    it.each([
        {
            variant: 'ECONNRESET code',
            makeError: (): Error => Object.assign(new Error('read failed'), { code: 'ECONNRESET' }),
        },
        { variant: 'aborted message', makeError: (): Error => new Error('aborted') },
        {
            variant: 'AbortError name',
            makeError: (): Error => Object.assign(new Error('This operation was aborted'), { name: 'AbortError' }),
        },
        {
            variant: 'premature close code',
            makeError: (): Error => Object.assign(new Error('Premature close'), { code: 'ERR_STREAM_PREMATURE_CLOSE' }),
        },
    ])('treats a mid-body $variant as a client disconnect, not a server error', async ({ makeError }) => {
        const infoSpy = vi.spyOn(logger, 'info')
        const errorSpy = vi.spyOn(logger, 'error')
        const config = makeConfig()
        const enc = new TextEncoder()
        const line = enc.encode(JSON.stringify({ seq: 1, event: { type: 'before-drop' } }) + '\n')
        let sentFirstChunk = false
        const body = new ReadableStream<Uint8Array>({
            pull(controller) {
                if (!sentFirstChunk) {
                    sentFirstChunk = true
                    controller.enqueue(line)
                    return
                }
                controller.error(makeError())
            },
        })

        const res = await handleIngest(makeContext({ body }), fakeRedis as unknown as Redis, config, [] as CryptoKey[])

        expect(res.status).toBe(408)
        const responseBody = (await decodeJson(res)) as { last_accepted_seq: number }
        expect(responseBody.last_accepted_seq).toBe(1)

        const entries = await fakeRedis.xrange(getStreamKey(RUN_ID))
        expect(entries).toHaveLength(1)

        const log = infoSpy.mock.calls.find((c) => c[0] === 'ingest:client_disconnect')?.[1] as Record<string, unknown>
        expect(log).toMatchObject({ run: RUN_ID, accepted: 1, lastSeq: 1 })
        expect(errorSpy).not.toHaveBeenCalledWith('http.unhandled_error', expect.anything())
    })

    // -----------------------------------------------------------------------
    // Empty body
    // -----------------------------------------------------------------------

    it('returns 200 with accepted=0 for an empty body', async () => {
        const config = makeConfig()
        const ctx = makeContext({ body: makeStringBody('') })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)
        const body = (await decodeJson(res)) as { accepted: number; duplicate: number; last_accepted_seq: number }
        expect(body.accepted).toBe(0)
        expect(body.duplicate).toBe(0)
        expect(body.last_accepted_seq).toBe(0)
    })

    // -----------------------------------------------------------------------
    // Side effects: turn-complete
    // -----------------------------------------------------------------------

    it('sets agent inactive and fires awaiting_input callback on turn-complete event', async () => {
        const fetchCalls: { url: string; body: unknown }[] = []
        const originalFetch = global.fetch
        global.fetch = vi.fn(async (url, init) => {
            fetchCalls.push({ url: String(url), body: JSON.parse(String((init as RequestInit).body)) })
            return new Response('', { status: 200 })
        }) as typeof fetch

        const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })
        mockValidate.mockResolvedValue(makeClaims())

        const turnCompleteEvent = {
            type: 'notification',
            notification: { method: '_posthog/turn_complete' },
        }
        const ndjson = JSON.stringify({ seq: 1, event: turnCompleteEvent }) + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)

        // Agent must have been set inactive.
        const agentActive = await redisStream.getAgentActive()
        expect(agentActive).toBe(false)

        // Flush any queued microtasks so the detached fire-and-forget promise runs.
        await new Promise((r) => setTimeout(r, 0))

        const callbackCall = fetchCalls.find((c) => c.url.includes('agent-proxy-callback'))
        expect(callbackCall).toBeTruthy()
        expect(callbackCall?.body).toMatchObject({ kind: 'awaiting_input', agent_active: false })

        global.fetch = originalFetch
    })

    // -----------------------------------------------------------------------
    // Side effects: session/update → agent active
    // -----------------------------------------------------------------------

    it('sets agent active on session/update event and fires heartbeat after claim', async () => {
        const fetchCalls: { url: string; body: unknown }[] = []
        const originalFetch = global.fetch
        global.fetch = vi.fn(async (url, init) => {
            fetchCalls.push({ url: String(url), body: JSON.parse(String((init as RequestInit).body)) })
            return new Response('', { status: 200 })
        }) as typeof fetch

        const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })
        mockValidate.mockResolvedValue(makeClaims())

        const sessionUpdateEvent = {
            type: 'notification',
            notification: { method: 'session/update' },
        }
        const ndjson = JSON.stringify({ seq: 1, event: sessionUpdateEvent }) + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)

        const agentActive = await redisStream.getAgentActive()
        expect(agentActive).toBe(true)

        await new Promise((r) => setTimeout(r, 0))

        const callbackCall = fetchCalls.find((c) => c.url.includes('agent-proxy-callback'))
        expect(callbackCall).toBeTruthy()
        expect(callbackCall?.body).toMatchObject({ kind: 'heartbeat', agent_active: true })

        global.fetch = originalFetch
    })

    // -----------------------------------------------------------------------
    // Side effects: heartbeat throttle
    // -----------------------------------------------------------------------

    it('does not fire second heartbeat callback when heartbeat key is already claimed', async () => {
        const fetchCalls: { url: string }[] = []
        const originalFetch = global.fetch
        global.fetch = vi.fn(async (url) => {
            fetchCalls.push({ url: String(url) })
            return new Response('', { status: 200 })
        }) as typeof fetch

        const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })

        // Pre-seed: set agent active so heartbeat path runs
        await redisStream.setAgentActive(true)
        // Claim the heartbeat key so the throttle fires (first heartbeat claimed)
        await redisStream.claimAgentActiveHeartbeat(HEARTBEAT_THROTTLE_SECONDS)

        const sessionUpdateEvent = {
            type: 'notification',
            notification: { method: 'session/update' },
        }
        const ndjson =
            [
                JSON.stringify({ seq: 1, event: sessionUpdateEvent }),
                JSON.stringify({ seq: 2, event: { type: 'other' } }),
            ].join('\n') + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)

        await new Promise((r) => setTimeout(r, 0))

        // The heartbeat key was already claimed; no callback should fire.
        const callbackCalls = fetchCalls.filter((c) => c.url.includes('agent-proxy-callback'))
        // session/update on seq 1 tries to claim → already claimed → no callback
        // seq 2 is a non-session-update event; agentActive is true; tries to claim → already claimed → no callback
        expect(callbackCalls.length).toBe(0)

        global.fetch = originalFetch
    })

    // -----------------------------------------------------------------------
    // Side effects: best-effort (callback failure does not fail ingest)
    // -----------------------------------------------------------------------

    it('still returns 200 when the Django callback throws', async () => {
        const originalFetch = global.fetch
        global.fetch = vi.fn(async () => {
            throw new Error('network failure')
        }) as typeof fetch

        const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })

        const turnCompleteEvent = {
            type: 'notification',
            notification: { method: '_posthog/turn_complete' },
        }
        const ndjson = JSON.stringify({ seq: 1, event: turnCompleteEvent }) + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        // Callback failure must NOT affect ingest response
        expect(res.status).toBe(200)

        // Let the detached promise settle without crashing the test
        await new Promise((r) => setTimeout(r, 10))

        global.fetch = originalFetch
    })

    it('still returns 200 when the Django callback returns a non-2xx status', async () => {
        const originalFetch = global.fetch
        global.fetch = vi.fn(async () => new Response('', { status: 500 })) as typeof fetch

        const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })

        const turnCompleteEvent = {
            type: 'notification',
            notification: { method: '_posthog/turn_complete' },
        }
        const ndjson = JSON.stringify({ seq: 1, event: turnCompleteEvent }) + '\n'
        const ctx = makeContext({ body: makeStringBody(ndjson) })
        const res = await handleIngest(ctx, fakeRedis as unknown as Redis, config, [] as CryptoKey[])
        expect(res.status).toBe(200)

        await new Promise((r) => setTimeout(r, 10))

        global.fetch = originalFetch
    })

    // -----------------------------------------------------------------------
    // heartbeatWorkflowIfNeeded (side-effects.ts) unit tests
    // -----------------------------------------------------------------------

    describe('heartbeatWorkflowIfNeeded', () => {
        it('sets agent inactive and fires awaiting_input for a turn-complete event', async () => {
            const fired: { kind: string }[] = []
            const originalFetch = global.fetch
            global.fetch = vi.fn(async (_, init) => {
                fired.push(JSON.parse(String((init as RequestInit).body)))
                return new Response('', { status: 200 })
            }) as typeof fetch

            const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })
            const event = { type: 'notification', notification: { method: '_posthog/turn_complete' } }
            await heartbeatWorkflowIfNeeded(redisStream, RUN_ID, event, TASK_ID, TEAM_ID, 'tok', config)

            expect(await redisStream.getAgentActive()).toBe(false)
            await new Promise((r) => setTimeout(r, 0))
            expect(fired.some((f) => f.kind === 'awaiting_input')).toBe(true)

            global.fetch = originalFetch
        })

        it('sets agent active and fires heartbeat for a session/update event', async () => {
            const fired: { kind: string }[] = []
            const originalFetch = global.fetch
            global.fetch = vi.fn(async (_, init) => {
                fired.push(JSON.parse(String((init as RequestInit).body)))
                return new Response('', { status: 200 })
            }) as typeof fetch

            const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })
            const event = { type: 'notification', notification: { method: 'session/update' } }
            await heartbeatWorkflowIfNeeded(redisStream, RUN_ID, event, TASK_ID, TEAM_ID, 'tok', config)

            expect(await redisStream.getAgentActive()).toBe(true)
            await new Promise((r) => setTimeout(r, 0))
            expect(fired.some((f) => f.kind === 'heartbeat')).toBe(true)

            global.fetch = originalFetch
        })

        it('does not fire heartbeat for a plain event when agent is not active', async () => {
            const fired: unknown[] = []
            const originalFetch = global.fetch
            global.fetch = vi.fn(async (_, init) => {
                fired.push(JSON.parse(String((init as RequestInit).body)))
                return new Response('', { status: 200 })
            }) as typeof fetch

            const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })
            const event = { type: 'notification', notification: { method: 'other' } }
            await heartbeatWorkflowIfNeeded(redisStream, RUN_ID, event, TASK_ID, TEAM_ID, 'tok', config)

            await new Promise((r) => setTimeout(r, 0))
            expect(fired).toHaveLength(0)

            global.fetch = originalFetch
        })

        it('fires heartbeat for a plain event when agent is already active', async () => {
            const fired: { kind: string }[] = []
            const originalFetch = global.fetch
            global.fetch = vi.fn(async (_, init) => {
                fired.push(JSON.parse(String((init as RequestInit).body)))
                return new Response('', { status: 200 })
            }) as typeof fetch

            await redisStream.setAgentActive(true)
            const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })
            const event = { type: 'notification', notification: { method: 'other' } }
            await heartbeatWorkflowIfNeeded(redisStream, RUN_ID, event, TASK_ID, TEAM_ID, 'tok', config)

            await new Promise((r) => setTimeout(r, 0))
            expect(fired.some((f) => f.kind === 'heartbeat')).toBe(true)

            global.fetch = originalFetch
        })

        it('skips the heartbeat callback when the throttle key is already claimed', async () => {
            const fired: unknown[] = []
            const originalFetch = global.fetch
            global.fetch = vi.fn(async (_, init) => {
                fired.push(JSON.parse(String((init as RequestInit).body)))
                return new Response('', { status: 200 })
            }) as typeof fetch

            await redisStream.setAgentActive(true)
            // Pre-claim the heartbeat slot
            await redisStream.claimAgentActiveHeartbeat(HEARTBEAT_THROTTLE_SECONDS)

            const config = makeConfig({ djangoCallbackBaseUrl: 'http://django' })
            const event = { type: 'notification', notification: { method: 'other' } }
            await heartbeatWorkflowIfNeeded(redisStream, RUN_ID, event, TASK_ID, TEAM_ID, 'tok', config)

            await new Promise((r) => setTimeout(r, 0))
            expect(fired).toHaveLength(0)

            global.fetch = originalFetch
        })

        it('does not fire any callback when djangoCallbackBaseUrl is empty', async () => {
            const fetchSpy = vi.spyOn(global, 'fetch')
            const config = makeConfig({ djangoCallbackBaseUrl: '' })
            const event = { type: 'notification', notification: { method: '_posthog/turn_complete' } }
            await heartbeatWorkflowIfNeeded(redisStream, RUN_ID, event, TASK_ID, TEAM_ID, 'tok', config)
            await new Promise((r) => setTimeout(r, 0))
            expect(fetchSpy).not.toHaveBeenCalled()
            fetchSpy.mockRestore()
        })
    })

    // -----------------------------------------------------------------------
    // Body-arrival timing diagnostic
    //
    // The ingest log carries chunks/bodyBytes/firstChunkMs/lastChunkMs/chunkSpanMs
    // so operators can tell a live upload (chunks spread over the request) from a
    // body buffered upstream and delivered in one burst at request close. If those
    // numbers are wrong the diagnostic misleads that investigation, so lock in that
    // they reflect the actual body read.
    // -----------------------------------------------------------------------

    describe('body-arrival timing', () => {
        it('reports chunk count, byte total, and a consistent span on the ingest log', async () => {
            const infoSpy = vi.spyOn(logger, 'info')
            const enc = new TextEncoder()
            const chunk1 = enc.encode(JSON.stringify({ seq: 1, event: { type: 'a' } }) + '\n')
            const chunk2 = enc.encode(JSON.stringify({ seq: 2, event: { type: 'b' } }) + '\n')

            const ctx = makeContext({ body: makeChunkedBody([chunk1, chunk2]) })
            const res = await handleIngest(ctx, fakeRedis as unknown as Redis, makeConfig(), [] as CryptoKey[])
            expect(res.status).toBe(200)

            const log = infoSpy.mock.calls.find((c) => c[0] === 'ingest')?.[1] as Record<string, number>
            expect(log).toBeTruthy()
            expect(log.chunks).toBe(2)
            expect(log.bodyBytes).toBe(chunk1.length + chunk2.length)
            const firstChunkMs = log.firstChunkMs as number
            const lastChunkMs = log.lastChunkMs as number
            expect(typeof firstChunkMs).toBe('number')
            expect(lastChunkMs).toBeGreaterThanOrEqual(firstChunkMs)
            expect(log.chunkSpanMs as number).toBe(lastChunkMs - firstChunkMs)
        })

        it('reports zero chunks and null timing for an empty body', async () => {
            const infoSpy = vi.spyOn(logger, 'info')

            const ctx = makeContext({ body: makeStringBody('') })
            const res = await handleIngest(ctx, fakeRedis as unknown as Redis, makeConfig(), [] as CryptoKey[])
            expect(res.status).toBe(200)

            const log = infoSpy.mock.calls.find((c) => c[0] === 'ingest')?.[1] as Record<string, unknown>
            expect(log).toBeTruthy()
            expect(log.chunks).toBe(0)
            expect(log.bodyBytes).toBe(0)
            expect(log.firstChunkMs).toBeNull()
            expect(log.lastChunkMs).toBeNull()
            expect(log.chunkSpanMs).toBeNull()
        })
    })
})
