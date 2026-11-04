import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const { resolveState } = vi.hoisted(() => ({ resolveState: vi.fn() }))

vi.mock('@/hono/request-state-resolver', () => ({
    RequestStateResolver: class {
        resolve = resolveState
    },
}))

import type { RedisLike } from '@/hono/cache/RedisCache'
import { McpDispatcher } from '@/hono/dispatcher'
import type { ResolvedState } from '@/hono/request-state-resolver'
import { ToolCatalog } from '@/hono/tool-catalog'
import type { RequestProperties } from '@/lib/request-properties'
import { DEFAULT_STATE_TTL_SECONDS, SignedStateCodec } from '@/lib/signed-state'
import {
    META_CLIENT_CAPABILITIES,
    META_CLIENT_INFO,
    META_PROTOCOL_VERSION,
    STATELESS_PROTOCOL_VERSION,
} from '@/lib/stateless-protocol'
import { setConfirmedActionRuntime } from '@/tools/confirmed-action-registry'
import type { ConfirmedActionRuntime } from '@/tools/confirmed-action-registry'

import { makeToolExecutorState } from '../shared/test-utils'
import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

const DECISION = {
    question: 'Roll the new checkout flag out to everyone?',
    options: [
        { id: 'ship', label: 'Ship it' },
        { id: 'hold', label: 'Hold' },
    ],
}

const props = { userHash: 'token-hash', apiToken: 'phx_synthetic' } as RequestProperties

let catalog: ToolCatalog
let now: number
let user: string

beforeAll(async () => {
    catalog = new ToolCatalog()
    await catalog.warmup()
})

beforeEach(() => {
    now = Date.UTC(2030, 0, 1)
    user = 'user-a'
    const codec = new SignedStateCodec(Buffer.alloc(32, 7), { now: () => now })
    setConfirmedActionRuntime({ codec } as unknown as ConfirmedActionRuntime)
})

afterEach(() => {
    setConfirmedActionRuntime(undefined)
    resolveState.mockReset()
})

function createRedis(): RedisLike {
    const store = new Map<string, string>()
    return {
        get: async (key: string) => store.get(key) ?? null,
        set: async (key: string, value: string) => {
            store.set(key, value)
            return 'OK'
        },
        del: async () => 0,
        scan: async () => ['0', []] as [string, string[]],
        ...makeRedisRateLimitStubs(store),
    } as RedisLike
}

function dispatcherFor(useSingleExec: boolean): McpDispatcher {
    const tools = catalog
        .getFilteredTools({ scopes: ['*'], featureFlags: { 'mcp-decision-request': true } })
        .filter((tool) => tool.name === 'decision-request')
    expect(tools).toHaveLength(1)
    resolveState.mockImplementation(async (): Promise<ResolvedState> => {
        const state = makeToolExecutorState(tools, { useSingleExec })
        state.context.getDistinctId = async () => user
        state.context.cache = { get: async () => undefined } as unknown as ResolvedState['context']['cache']
        return state
    })
    return new McpDispatcher(catalog, createRedis())
}

function statelessParams(
    useSingleExec: boolean,
    decision: Record<string, unknown> = DECISION,
    capabilities: Record<string, unknown> = { elicitation: { form: {} } }
): Record<string, unknown> {
    return {
        ...(useSingleExec
            ? { name: 'exec', arguments: { command: `call decision-request ${JSON.stringify(decision)}` } }
            : { name: 'decision-request', arguments: decision }),
        _meta: {
            [META_PROTOCOL_VERSION]: STATELESS_PROTOCOL_VERSION,
            [META_CLIENT_INFO]: { name: 'synthetic-client', version: '1.0.0' },
            [META_CLIENT_CAPABILITIES]: capabilities,
        },
    }
}

async function call(dispatcher: McpDispatcher, params: Record<string, unknown>): Promise<Record<string, any>> {
    const response = await dispatcher.handleRequest(
        new Request('https://mcp.test/mcp', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'MCP-Protocol-Version': STATELESS_PROTOCOL_VERSION,
                'Mcp-Method': 'tools/call',
                'Mcp-Name': String(params.name),
            },
            body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params }),
        }),
        props
    )
    return ((await response.json()) as { result: Record<string, any> }).result
}

function resultText(result: Record<string, any>): string {
    return (result.content as { text: string }[]).map((part) => part.text).join('\n')
}

describe('decision-request through the dispatcher', () => {
    it.each([false, true])(
        'asks a stateless form client and returns its choice (single exec: %s)',
        async (useSingleExec) => {
            const dispatcher = dispatcherFor(useSingleExec)
            const first = await call(dispatcher, statelessParams(useSingleExec))
            expect(first).toMatchObject({
                resultType: 'input_required',
                requestState: expect.any(String),
                inputRequests: {
                    decision: {
                        method: 'elicitation/create',
                        params: { mode: 'form', message: DECISION.question },
                    },
                },
            })

            const answered = await call(dispatcher, {
                ...statelessParams(useSingleExec),
                requestState: first.requestState,
                inputResponses: { decision: { action: 'accept', content: { choice: 'hold', note: 'After launch' } } },
            })
            expect(answered.resultType).toBe('complete')
            expect(resultText(answered)).toContain('answered')
            expect(resultText(answered)).toContain('hold')
            expect(resultText(answered)).toContain('After launch')
        }
    )

    it.each<[string, (state: { requestState: string; params: Record<string, unknown> }) => void, string]>([
        [
            'a tampered request state',
            (retry) => {
                retry.requestState = `${retry.requestState.slice(0, -2)}${retry.requestState.endsWith('AA') ? 'BB' : 'AA'}`
            },
            'not one this server issued',
        ],
        [
            'an expired request state',
            () => {
                now += (DEFAULT_STATE_TTL_SECONDS + 1) * 1000
            },
            'expired',
        ],
        [
            'an answer from a different user',
            () => {
                user = 'user-b'
            },
            'different user',
        ],
        [
            'a choice that was never offered',
            (retry) => {
                retry.params.inputResponses = { decision: { action: 'accept', content: { choice: 'delete' } } }
            },
            'does not match any requested option',
        ],
        [
            'options changed after the user was asked',
            (retry) => {
                Object.assign(
                    retry.params,
                    statelessParams(false, {
                        ...DECISION,
                        options: [DECISION.options[0], { id: 'delete', label: 'Hold' }],
                    })
                )
                retry.params.inputResponses = { decision: { action: 'accept', content: { choice: 'delete' } } }
            },
            'changed after the user was asked',
        ],
    ])('rejects %s', async (_name, perturb, expected) => {
        const dispatcher = dispatcherFor(false)
        const first = await call(dispatcher, statelessParams(false))
        const retry = {
            requestState: first.requestState as string,
            params: {
                ...statelessParams(false),
                inputResponses: { decision: { action: 'accept', content: { choice: 'ship' } } },
            } as Record<string, unknown>,
        }
        perturb(retry)

        const result = await call(dispatcher, { ...retry.params, requestState: retry.requestState })

        expect(result.resultType).toBe('complete')
        expect(resultText(result)).not.toContain('answered')
        expect(resultText(result)).toContain(expected)
    })

    it('tells a stateless client without form elicitation to ask in chat', async () => {
        const result = await call(dispatcherFor(false), statelessParams(false, DECISION, { elicitation: { url: {} } }))

        expect(result.resultType).toBe('complete')
        expect(resultText(result)).toContain('unsupported_client')
    })

    it.each(['2025-11-25', STATELESS_PROTOCOL_VERSION] as const)(
        'round-trips with the SDK client on %s',
        async (version) => {
            const dispatcher = dispatcherFor(false)
            const client = new Client(
                { name: 'decision-test', version: '1.0.0' },
                {
                    capabilities: { elicitation: { form: {} } },
                    versionNegotiation: { mode: version === STATELESS_PROTOCOL_VERSION ? { pin: version } : 'legacy' },
                }
            )
            const onElicit = vi.fn(async () => ({ action: 'accept' as const, content: { choice: 'ship' } }))
            client.setRequestHandler('elicitation/create', onElicit)
            const transport = new StreamableHTTPClientTransport(new URL('https://mcp.test/mcp'), {
                fetch: async (input, init) => dispatcher.handleRequest(new Request(input, init), { ...props }),
            })
            try {
                await client.connect(transport)
                const result = await client.callTool({ name: 'decision-request', arguments: DECISION })
                const text = resultText(result as Record<string, any>)
                if (version === STATELESS_PROTOCOL_VERSION) {
                    expect(onElicit).toHaveBeenCalledTimes(1)
                    expect(text).toContain('answered')
                    expect(text).toContain('ship')
                } else {
                    expect(onElicit).not.toHaveBeenCalled()
                    expect(text).toContain('unsupported_client')
                }
            } finally {
                await client.close()
            }
        }
    )
})
