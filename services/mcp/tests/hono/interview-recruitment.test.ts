import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { resolveState, executeTool } = vi.hoisted(() => ({ resolveState: vi.fn(), executeTool: vi.fn() }))

vi.mock('@/hono/request-state-resolver', () => ({
    RequestStateResolver: class {
        resolve = resolveState
    },
}))
vi.mock('@/hono/tool-executor', () => ({
    ToolExecutor: class {
        handleToolCall = executeTool
    },
}))

import type { RedisLike } from '@/hono/cache/RedisCache'
import { McpDispatcher } from '@/hono/dispatcher'
import { MCP_INTERVIEW_RECRUITMENT_FLAG } from '@/hono/interview-recruitment'
import type { ResolvedState } from '@/hono/request-state-resolver'
import type { ToolCatalog } from '@/hono/tool-catalog'
import type { RequestProperties } from '@/lib/request-properties'
import {
    META_CLIENT_CAPABILITIES,
    META_CLIENT_INFO,
    META_PROTOCOL_VERSION,
    STATELESS_PROTOCOL_VERSION,
} from '@/lib/stateless-protocol'

function createRedis(): {
    redis: RedisLike
    entries: Map<string, { value: string; expires?: number }>
} {
    const entries = new Map<string, { value: string; expires?: number }>()
    const get = (key: string): string | undefined => {
        const entry = entries.get(key)
        if (entry?.expires !== undefined && entry.expires <= Date.now()) {
            entries.delete(key)
            return undefined
        }
        return entry?.value
    }
    const redis = {
        eval: vi.fn(async (_script: string, _numberOfKeys: number, ...args: (string | number)[]) => {
            const [preference, pending, first, second, ttl, pendingTtl] = args as [
                string,
                string,
                string,
                string,
                number,
                number | undefined,
            ]
            if (pendingTtl !== undefined) {
                if (get(preference) !== undefined) {
                    return 0
                }
                entries.set(preference, { value: first, expires: Date.now() + ttl * 1000 })
                entries.set(pending, { value: second, expires: Date.now() + pendingTtl * 1000 })
            } else {
                if (get(pending) !== first) {
                    return 0
                }
                entries.set(preference, { value: second, ...(ttl ? { expires: Date.now() + ttl * 1000 } : {}) })
                entries.delete(pending)
            }
            return 1
        }),
    } as unknown as RedisLike
    return { redis, entries }
}

function makeState(): ResolvedState {
    return {
        distinctId: 'test-person',
        context: { api: { getProjectBaseUrl: () => 'https://us.posthog.com' } },
        toolFeatureFlags: { [MCP_INTERVIEW_RECRUITMENT_FLAG]: true },
        clientProfile: { capabilities: { supportsInstructions: false } },
    } as unknown as ResolvedState
}

const props = { userHash: 'token-hash', apiToken: 'phx_test' } as RequestProperties
const toolResult = { content: [{ type: 'text', text: 'Original tool result' }] }

function callParams(capabilities: Record<string, unknown> = { elicitation: { form: {} } }): Record<string, unknown> {
    return {
        name: 'exec',
        arguments: { command: 'call project-get {}' },
        _meta: {
            [META_PROTOCOL_VERSION]: STATELESS_PROTOCOL_VERSION,
            [META_CLIENT_INFO]: { name: 'test-client', version: '1.0.0' },
            [META_CLIENT_CAPABILITIES]: capabilities,
        },
    }
}

function request(params: Record<string, unknown>): Request {
    return new Request('https://mcp.test/mcp', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'MCP-Protocol-Version': STATELESS_PROTOCOL_VERSION,
            'Mcp-Method': 'tools/call',
            'Mcp-Name': String(params.name),
        },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params }),
    })
}

async function call(
    dispatcher: McpDispatcher,
    params = callParams(),
    requestProps = props
): Promise<{ result?: Record<string, unknown>; error?: { code: number } }> {
    return (await dispatcher.handleRequest(request(params), requestProps)).json()
}

function continuation(requestState: unknown, response: unknown): Record<string, unknown> {
    return { ...callParams(), requestState, inputResponses: { 'mcp-interview': response } }
}

describe('MCP interview recruitment', () => {
    let state: ResolvedState
    let storage: ReturnType<typeof createRedis>
    let dispatcher: McpDispatcher

    beforeEach(() => {
        vi.clearAllMocks()
        state = makeState()
        resolveState.mockResolvedValue(state)
        executeTool.mockResolvedValue(toolResult)
        storage = createRedis()
        dispatcher = new McpDispatcher({} as ToolCatalog, storage.redis)
    })

    afterEach(() => vi.useRealTimers())

    it.each([
        { action: 'accept', content: { response: 'interested' } },
        { action: 'accept', content: { response: 'do_not_ask_again' } },
        { action: 'decline' },
    ])('persists $action/$content and suppresses across reconnects and tokens until reset', async (answer) => {
        const invitation = await call(dispatcher)
        expect(invitation.result).toMatchObject({
            resultType: 'input_required',
            inputRequests: { 'mcp-interview': { method: 'elicitation/create', params: { mode: 'form' } } },
        })
        expect(executeTool).not.toHaveBeenCalled()

        const resumed = await call(dispatcher, continuation(invitation.result?.requestState, answer))
        expect(resumed.result).toMatchObject({ resultType: 'complete', ...toolResult })
        expect(executeTool).toHaveBeenCalledTimes(1)
        const [key, record] = [...storage.entries.entries()][0]!
        expect(record.expires).toBeUndefined()
        expect(JSON.parse(record.value)).toMatchObject({
            distinct_id: 'test-person',
            response: answer.action === 'decline' ? 'do_not_ask_again' : answer.content!.response,
        })

        vi.useFakeTimers()
        vi.setSystemTime(Date.now() + 365 * 24 * 60 * 60 * 1000)
        const reconnected = new McpDispatcher({} as ToolCatalog, storage.redis)
        expect((await call(reconnected, callParams(), { ...props, userHash: 'new-token' })).result).toMatchObject(
            toolResult
        )
        storage.entries.delete(key)
        expect((await call(reconnected)).result?.resultType).toBe('input_required')
    })

    it.each([{ action: 'cancel' }, { action: 'accept', content: { response: 'not_now' } }])(
        'lets $action/$content continue and asks again after the cooldown',
        async (answer) => {
            vi.useFakeTimers()
            const invitation = await call(dispatcher)
            await call(dispatcher, continuation(invitation.result?.requestState, answer))
            expect((await call(dispatcher)).result).toMatchObject(toolResult)
            vi.setSystemTime(Date.now() + 7 * 24 * 60 * 60 * 1000)
            expect((await call(dispatcher)).result?.resultType).toBe('input_required')
        }
    )

    it.each([{}, { elicitation: { url: {} } }, { elicitation: false }])(
        'skips clients without form support: %j',
        async (capabilities) => {
            expect((await call(dispatcher, callParams(capabilities))).result).toMatchObject(toolResult)
            expect(storage.entries.size).toBe(0)
        }
    )

    it('accepts the backwards-compatible empty elicitation capability', async () => {
        expect((await call(dispatcher, callParams({ elicitation: {} }))).result?.resultType).toBe('input_required')
    })

    it.each(['disabled', 'missing', 'impersonated', 'suppressed'])('skips recruitment when %s', async (condition) => {
        if (condition === 'disabled' || condition === 'missing') {
            state.toolFeatureFlags = condition === 'disabled' ? { [MCP_INTERVIEW_RECRUITMENT_FLAG]: false } : {}
        }
        state.isImpersonated = condition === 'impersonated'
        state.suppressAnalytics = condition === 'suppressed'
        expect((await call(dispatcher)).result).toMatchObject(toolResult)
        expect(storage.entries.size).toBe(0)
    })

    it('reserves only one invitation across simultaneous calls and server instances', async () => {
        const other = new McpDispatcher({} as ToolCatalog, storage.redis)
        const results = await Promise.all([call(dispatcher), call(other)])
        expect(results.filter((r) => r.result?.resultType === 'input_required')).toHaveLength(1)
        expect(executeTool).toHaveBeenCalledTimes(1)
    })

    it('does not prompt legacy clients', async () => {
        const legacy = new Request('https://mcp.test/mcp', {
            method: 'POST',
            body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'exec' } }),
        })
        const result = (await (await dispatcher.handleRequest(legacy, props)).json()) as { result: unknown }
        expect(result.result).toEqual(toolResult)
        expect(storage.entries.size).toBe(0)
    })

    it.each(['token', 'person', 'arguments', 'expired', 'replayed', 'invalid-answer'])(
        'rejects a %s continuation without executing the tool',
        async (change) => {
            vi.useFakeTimers()
            const invitation = await call(dispatcher)
            const resumed = continuation(invitation.result?.requestState, {
                action: 'accept',
                content: { response: 'do_not_ask_again' },
            })
            let continuationProps = props
            if (change === 'token') {
                continuationProps = { ...props, userHash: 'another-token' }
            } else if (change === 'person') {
                state.distinctId = 'another-person'
            } else if (change === 'arguments') {
                resumed.arguments = { command: 'call project-delete {}' }
            } else if (change === 'expired') {
                vi.setSystemTime(Date.now() + 10 * 60 * 1000)
            } else if (change === 'replayed') {
                await call(dispatcher, resumed)
                executeTool.mockClear()
            } else {
                resumed.inputResponses = { 'mcp-interview': { action: 'accept', content: {} } }
            }
            expect((await call(dispatcher, resumed, continuationProps)).error?.code).toBe(-32602)
            expect(executeTool).not.toHaveBeenCalled()
        }
    )

    it('processes a displayed form after its flag has been disabled', async () => {
        const invitation = await call(dispatcher)
        state.toolFeatureFlags = {}
        expect(
            (await call(dispatcher, continuation(invitation.result?.requestState, { action: 'decline' }))).result
        ).toMatchObject(toolResult)
        expect(JSON.parse([...storage.entries.values()][0]!.value).response).toBe('do_not_ask_again')
    })

    it('skips the invitation if Redis fails, but retries a response write before executing the tool', async () => {
        vi.mocked(storage.redis.eval).mockRejectedValueOnce(new Error('unavailable'))
        expect((await call(dispatcher)).result).toMatchObject(toolResult)
        executeTool.mockClear()
        const invitation = await call(dispatcher)
        const resumed = continuation(invitation.result?.requestState, { action: 'decline' })
        vi.mocked(storage.redis.eval).mockRejectedValueOnce(new Error('unavailable'))
        expect((await call(dispatcher, resumed)).error?.code).toBe(-32603)
        expect(executeTool).not.toHaveBeenCalled()
        expect((await call(dispatcher, resumed)).result).toMatchObject(toolResult)
    })

    it('completes the form round trip with the official MCP client', async () => {
        const client = new Client(
            { name: 'recruitment-test', version: '1.0.0' },
            { capabilities: { elicitation: { form: {} } }, versionNegotiation: { mode: { pin: '2026-07-28' } } }
        )
        const onForm = vi.fn(async () => ({ action: 'accept' as const, content: { response: 'interested' } }))
        client.setRequestHandler('elicitation/create', onForm)
        const transport = new StreamableHTTPClientTransport(new URL('https://mcp.test/mcp'), {
            fetch: async (input, init) => dispatcher.handleRequest(new Request(input, init), props),
        })
        try {
            await client.connect(transport)
            const result = await client.callTool({ name: 'exec', arguments: { command: 'call project-get {}' } })
            expect(result).toMatchObject(toolResult)
            expect(onForm).toHaveBeenCalledTimes(1)
            expect(executeTool).toHaveBeenCalledTimes(1)
        } finally {
            await client.close()
        }
    })
})
