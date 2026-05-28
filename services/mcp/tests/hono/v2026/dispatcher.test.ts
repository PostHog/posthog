import { describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { buildSharedDeps, McpDispatcher, type SharedDispatcherDeps } from '@/hono/dispatcher'
import { ToolCatalog } from '@/hono/tool-catalog'
import { V2026HandshakeStrategy } from '@/hono/v2026/handshake'
import { RequestStateCodec } from '@/hono/v2026/request-state'
import { buildV2026Strategy } from '@/hono/v2026/tool-call'
import type { Context } from '@/tools/types'

import { makeRedisRateLimitStubs } from '../helpers/redis-rate-limit-stubs'

const V = '2026-07-28'

function inMemoryRedis(): RedisLike {
    const store = new Map<string, string>()
    return {
        get: async (key) => store.get(key) ?? null,
        set: async (key, value) => {
            store.set(key, String(value))
            return 'OK'
        },
        del: async (...keys) => {
            let n = 0
            for (const k of keys) {
                if (store.delete(k)) {
                    n++
                }
            }
            return n
        },
        scan: async (cursor) => {
            const cur = String(cursor)
            return [cur === '0' ? 'next' : '0', cur === '0' ? Array.from(store.keys()) : []] as [string, string[]]
        },
        ...makeRedisRateLimitStubs(),
    }
}

function makeCodec(): RequestStateCodec {
    return new RequestStateCodec(Buffer.alloc(32, 0x42), undefined, {
        now: () => 1_700_000_000_000,
        randomNonce: () => 'fixed',
    })
}

interface TestRig {
    dispatcher: McpDispatcher
    codec: RequestStateCodec
    shared: SharedDispatcherDeps
}

function makeDispatcher(): TestRig {
    const codec = makeCodec()
    const shared = buildSharedDeps(new ToolCatalog(), inMemoryRedis())
    const strategy = buildV2026Strategy({
        codec,
        toolExecutor: shared.toolExecutor,
        handshake: new V2026HandshakeStrategy(shared.instructionsBuilder),
    })
    return { dispatcher: new McpDispatcher(shared, strategy), codec, shared }
}

type ExecutorFn = (params: unknown, props: unknown, state: { context: Context }) => Promise<unknown>

/**
 * Stub out the shared tool executor and state resolver so the test can
 * control what the handler does and inspect the dispatcher's response
 * shape without spinning up a real catalog + upstream API.
 */
function stubExecutorAndState(shared: SharedDispatcherDeps, onCall: ExecutorFn): void {
    ;(shared.toolExecutor as unknown as { handleToolCall: typeof onCall }).handleToolCall = vi.fn(onCall)
    shared.stateResolver.resolve = vi.fn(async () => ({
        reqCtx: {
            getContext: async () => ({}),
            getSessionUuid: async () => undefined,
        },
        context: {} as never,
        distinctId: 'did',
        version: 1,
        useSingleExec: false,
        apiKeyScopes: [],
        clientProfile: {} as never,
        allTools: [],
    })) as never
}

function makeReq(opts: {
    method: string
    body: Record<string, unknown>
    extraHeaders?: Record<string, string>
}): Request {
    return new Request('http://localhost/mcp', {
        method: 'POST',
        headers: {
            'mcp-protocol-version': V,
            'mcp-method': opts.method,
            'content-type': 'application/json',
            ...opts.extraHeaders,
        },
        body: JSON.stringify(opts.body),
    })
}

function withMeta(method: string, params: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        jsonrpc: '2.0',
        id: 1,
        method,
        params: {
            ...params,
            _meta: {
                'io.modelcontextprotocol/protocolVersion': V,
                'io.modelcontextprotocol/clientInfo': { name: 'test', version: '0' },
                'io.modelcontextprotocol/clientCapabilities': {},
            },
        },
    }
}

function mockProps(userHash: string = 'user-hash-1'): import('@/lib/request-properties').RequestProperties {
    return {
        apiToken: 'phx_test',
        userHash,
        version: 1,
    }
}

describe('McpDispatcher (v2026 strategy) — request validation', () => {
    it('rejects requests missing the protocol version header', async () => {
        const { dispatcher } = makeDispatcher()
        const req = new Request('http://localhost/mcp', {
            method: 'POST',
            headers: { 'mcp-method': 'ping', 'content-type': 'application/json' },
            body: JSON.stringify(withMeta('ping')),
        })
        const res = await dispatcher.handleRequest(req, mockProps())
        expect(res.status).toBe(400)
        const body = (await res.json()) as { error: { code: number } }
        expect(body.error.code).toBe(-32602)
    })

    it('rejects an unsupported protocol version with code -32004 + data.supported', async () => {
        const { dispatcher } = makeDispatcher()
        const req = new Request('http://localhost/mcp', {
            method: 'POST',
            headers: {
                'mcp-protocol-version': '1999-01-01',
                'mcp-method': 'ping',
                'content-type': 'application/json',
            },
            body: JSON.stringify(withMeta('ping')),
        })
        const res = await dispatcher.handleRequest(req, mockProps())
        expect(res.status).toBe(400)
        const body = (await res.json()) as { error: { code: number; data: { supported: string[] } } }
        expect(body.error.code).toBe(-32004)
        expect(body.error.data.supported).toEqual([V])
    })

    it('rejects header/body method mismatch', async () => {
        const { dispatcher } = makeDispatcher()
        const req = new Request('http://localhost/mcp', {
            method: 'POST',
            headers: {
                'mcp-protocol-version': V,
                'mcp-method': 'tools/call',
                'content-type': 'application/json',
            },
            body: JSON.stringify(withMeta('tools/list')),
        })
        const res = await dispatcher.handleRequest(req, mockProps())
        expect(res.status).toBe(400)
    })

    it('rejects malformed JSON with a parse error', async () => {
        const { dispatcher } = makeDispatcher()
        const req = new Request('http://localhost/mcp', {
            method: 'POST',
            headers: {
                'mcp-protocol-version': V,
                'mcp-method': 'ping',
                'content-type': 'application/json',
            },
            body: '{not json',
        })
        const res = await dispatcher.handleRequest(req, mockProps())
        expect(res.status).toBe(200)
        const body = (await res.json()) as { error: { code: number } }
        expect(body.error.code).toBe(-32700)
    })

    it('rejects batches (not supported in 2026-07-28)', async () => {
        const { dispatcher } = makeDispatcher()
        const req = new Request('http://localhost/mcp', {
            method: 'POST',
            headers: {
                'mcp-protocol-version': V,
                'mcp-method': 'ping',
                'content-type': 'application/json',
            },
            body: JSON.stringify([withMeta('ping')]),
        })
        const res = await dispatcher.handleRequest(req, mockProps())
        expect(res.status).toBe(400)
        const body = (await res.json()) as { error: { message: string } }
        expect(body.error.message).toMatch(/batches/i)
    })

    it('rejects unknown methods with -32601', async () => {
        const { dispatcher, shared } = makeDispatcher()
        stubExecutorAndState(shared, async () => null)
        const res = await dispatcher.handleRequest(
            makeReq({ method: 'fictional/method', body: withMeta('fictional/method') }),
            mockProps()
        )
        const body = (await res.json()) as { error: { code: number } }
        expect(body.error.code).toBe(-32601)
    })
})

describe('McpDispatcher (v2026 strategy) — ping', () => {
    it('returns a result with empty object', async () => {
        const { dispatcher } = makeDispatcher()
        const res = await dispatcher.handleRequest(makeReq({ method: 'ping', body: withMeta('ping') }), mockProps())
        expect(res.status).toBe(200)
        const body = (await res.json()) as { result: unknown }
        expect(body.result).toEqual({})
    })
})

describe('McpDispatcher (v2026 strategy) — requestState round-trip via tools/call', () => {
    it('returns input_required + signed requestState when the handler throws InputRequiredSignal', async () => {
        const { dispatcher, shared } = makeDispatcher()
        stubExecutorAndState(shared, async (_params, _props, state) => {
            await state.context.requestInput!({
                key: 'confirm',
                message: 'Proceed?',
                requestedSchema: { type: 'object', properties: {} },
            })
            return null
        })

        const res = await dispatcher.handleRequest(
            makeReq({
                method: 'tools/call',
                body: withMeta('tools/call', { name: 'sample-tool', arguments: {} }),
                extraHeaders: { 'mcp-name': 'sample-tool' },
            }),
            mockProps()
        )

        expect(res.status).toBe(200)
        const body = (await res.json()) as {
            result: { resultType: string; inputRequests: Record<string, unknown>; requestState: string }
        }
        expect(body.result.resultType).toBe('input_required')
        expect(body.result.inputRequests.confirm).toMatchObject({
            method: 'elicitation/create',
            params: { mode: 'form', message: 'Proceed?' },
        })
        expect(typeof body.result.requestState).toBe('string')
        expect(body.result.requestState.split('.')).toHaveLength(3)
    })

    it('decodes prior requestState on retry and returns the answer from requestInput', async () => {
        const { dispatcher, codec, shared } = makeDispatcher()
        const userHash = 'user-1'
        const requestState = codec.encode({
            sub: userHash,
            tool: 'sample-tool',
            round: 1,
            payload: { priorAnswers: {} },
        })

        let resolvedAnswer: unknown
        stubExecutorAndState(shared, async (_params, _props, state) => {
            resolvedAnswer = await state.context.requestInput!({
                key: 'confirm',
                message: 'Proceed?',
                requestedSchema: { type: 'object', properties: {} },
            })
            return { ok: true }
        })

        const res = await dispatcher.handleRequest(
            makeReq({
                method: 'tools/call',
                body: withMeta('tools/call', {
                    name: 'sample-tool',
                    arguments: {},
                    inputResponses: { confirm: { action: 'accept' } },
                    requestState,
                }),
                extraHeaders: { 'mcp-name': 'sample-tool' },
            }),
            mockProps(userHash)
        )

        expect(res.status).toBe(200)
        const body = (await res.json()) as { result: { resultType: string; ok?: boolean } }
        expect(body.result.resultType).toBe('complete')
        expect(body.result.ok).toBe(true)
        expect(resolvedAnswer).toEqual({ action: 'accept' })
    })

    it('rejects a requestState signed under a different userHash', async () => {
        const { dispatcher, codec, shared } = makeDispatcher()
        stubExecutorAndState(shared, async () => null)
        const stolen = codec.encode({
            sub: 'victim-hash',
            tool: 'sample-tool',
            round: 1,
            payload: { priorAnswers: {} },
        })

        const res = await dispatcher.handleRequest(
            makeReq({
                method: 'tools/call',
                body: withMeta('tools/call', {
                    name: 'sample-tool',
                    arguments: {},
                    inputResponses: { confirm: { action: 'accept' } },
                    requestState: stolen,
                }),
                extraHeaders: { 'mcp-name': 'sample-tool' },
            }),
            mockProps('attacker-hash')
        )
        expect(res.status).toBe(400)
        const body = (await res.json()) as { error: { code: number; message: string } }
        expect(body.error.code).toBe(-32602)
        expect(body.error.message).toMatch(/requestState rejected/)
    })

    it('rejects an inputResponses entry that is not a valid ElicitResult', async () => {
        const { dispatcher, shared } = makeDispatcher()
        stubExecutorAndState(shared, async () => null)

        const res = await dispatcher.handleRequest(
            makeReq({
                method: 'tools/call',
                body: withMeta('tools/call', {
                    name: 'sample-tool',
                    arguments: {},
                    inputResponses: { confirm: { not: 'a valid result' } },
                }),
                extraHeaders: { 'mcp-name': 'sample-tool' },
            }),
            mockProps()
        )
        expect(res.status).toBe(400)
        const body = (await res.json()) as { error: { code: number; message: string } }
        expect(body.error.code).toBe(-32602)
        expect(body.error.message).toMatch(/inputResponses\.confirm/)
    })
})
