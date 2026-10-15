import { Client, StreamableHTTPClientTransport } from '@modelcontextprotocol/client'
import { Hono } from 'hono'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { resolveState, executeTool, captureRecruitment } = vi.hoisted(() => ({
    resolveState: vi.fn(),
    executeTool: vi.fn(),
    captureRecruitment: vi.fn(),
}))

vi.mock('@/lib/posthog', () => ({ getPostHogClient: () => ({ capture: captureRecruitment }) }))

vi.mock('@/hono/request-state-resolver', () => ({
    RequestStateResolver: class {
        resolve = resolveState
    },
}))
vi.mock('@/hono/tool-executor', () => ({
    ToolExecutor: class {
        async handleToolCall(
            params: Record<string, unknown>,
            state: ResolvedState,
            hooks?: ToolCallHooks
        ): Promise<unknown> {
            const invitation = await hooks?.beforeExecute(state)
            if (invitation) {
                return invitation
            }
            const result = await executeTool(params, state)
            await hooks?.afterExecute(state, result)
            return result
        }
    },
}))

import type { RedisLike } from '@/hono/cache/RedisCache'
import { McpDispatcher } from '@/hono/dispatcher'
import { resolveInterviewRecruitmentConfig } from '@/hono/interview-recruitment'
import { registerPublicRoutes } from '@/hono/public-routes'
import type { ResolvedState } from '@/hono/request-state-resolver'
import type { ToolCatalog } from '@/hono/tool-catalog'
import type { ToolCallHooks } from '@/hono/tool-executor'
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
        get: vi.fn(async (key: string) => get(key) ?? null),
        set: vi.fn(async (key: string, value: string, ...args: (string | number)[]) => {
            if (args.includes('NX') && get(key) !== undefined) {
                return null
            }
            const ttlIndex = args.indexOf('EX')
            entries.set(key, {
                value,
                ...(ttlIndex >= 0 ? { expires: Date.now() + Number(args[ttlIndex + 1]) * 1000 } : {}),
            })
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => keys.reduce((count, key) => count + Number(entries.delete(key)), 0)),
        eval: vi.fn(async (_script: string, numberOfKeys: number, ...args: (string | number)[]) => {
            if (numberOfKeys === 1) {
                const [key, now, ttl, request] = args as [string, number, number, string]
                const record = JSON.parse(get(key) ?? JSON.stringify({ started: now, completed: 0, requests: [] })) as {
                    started: number
                    completed: number
                    requests: string[]
                }
                if (request && record.completed < 1000 && !record.requests.includes(request)) {
                    record.completed++
                    record.requests.push(request)
                }
                entries.set(key, { value: JSON.stringify(record), expires: now + ttl * 1000 })
                return [record.completed, record.started]
            }
            const [preference, pending, first, second, ttl, extra, consumedTtl] = args as [
                string,
                string,
                string,
                string,
                number,
                string | number,
                number | undefined,
            ]
            if (consumedTtl === undefined) {
                if (get(preference) !== undefined) {
                    return 0
                }
                entries.set(preference, { value: first, expires: Date.now() + ttl * 1000 })
                entries.set(pending, { value: second, expires: Date.now() + Number(extra) * 1000 })
            } else {
                if (get(pending) !== first) {
                    return 0
                }
                entries.set(preference, { value: second, ...(ttl ? { expires: Date.now() + ttl * 1000 } : {}) })
                entries.set(pending, { value: String(extra), expires: Date.now() + consumedTtl * 1000 })
            }
            return 1
        }),
    } as unknown as RedisLike
    return { redis, entries }
}

function makeState(): ResolvedState {
    return {
        distinctId: 'test-person',
        context: {
            api: { getProjectBaseUrl: () => 'https://us.posthog.com' },
            stateManager: { getOrgID: vi.fn(async () => 'org-1'), getProjectId: vi.fn(async () => '1') },
        },
        interviewRecruitmentConfig: resolveInterviewRecruitmentConfig(true, {
            message: 'Synthetic MCP interview',
            booking_url: 'https://example.com/book',
            min_completed_tool_calls: 0,
            min_session_age_seconds: 0,
        }),
        requestContext: { mcpConversationId: 'conversation-a', mcpClientName: 'test-client' },
        allTools: [{ name: 'project-get' }, { name: 'skill-get' }, { name: 'docs-search' }],
        clientProfile: { capabilities: { supportsInstructions: false } },
    } as unknown as ResolvedState
}

const props = { userHash: 'token-hash', apiToken: 'phx_test' } as RequestProperties
const toolResult = { content: [{ type: 'text', text: 'Original tool result' }] }

function callParams(capabilities: Record<string, unknown> = { elicitation: { url: {} } }): Record<string, unknown> {
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

let nextRequestId = 1

function request(params: Record<string, unknown>, id: number): Request {
    return new Request('https://mcp.test/mcp', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'MCP-Protocol-Version': STATELESS_PROTOCOL_VERSION,
            'Mcp-Method': 'tools/call',
            'Mcp-Name': String(params.name),
        },
        body: JSON.stringify({ jsonrpc: '2.0', id, method: 'tools/call', params }),
    })
}

async function call(
    dispatcher: McpDispatcher,
    params = callParams(),
    requestProps = props,
    id?: number
): Promise<{ result?: Record<string, unknown>; error?: { code: number; message: string } }> {
    return (await dispatcher.handleRequest(request(params, id ?? nextRequestId++), requestProps)).json()
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
        nextRequestId = 1
        state = makeState()
        resolveState.mockResolvedValue(state)
        executeTool.mockResolvedValue(toolResult)
        storage = createRedis()
        dispatcher = new McpDispatcher({} as ToolCatalog, storage.redis)
    })

    afterEach(() => vi.useRealTimers())

    it.each([{ action: 'accept' }, { action: 'decline' }])(
        'persists $action and suppresses across reconnects and tokens until reset',
        async (answer) => {
            const invitation = await call(dispatcher)
            expect(invitation.result).toMatchObject({
                resultType: 'input_required',
                inputRequests: {
                    'mcp-interview': {
                        method: 'elicitation/create',
                        params: {
                            mode: 'url',
                            url: `https://mcp.test/interview/${String(invitation.result?.requestState).slice('mcp-interview:'.length)}`,
                            message: state.interviewRecruitmentConfig!.message,
                        },
                    },
                },
            })
            expect(executeTool).not.toHaveBeenCalled()
            expect(captureRecruitment).toHaveBeenCalledWith(
                expect.objectContaining({
                    event: 'mcp interview invitation sent',
                    distinctId: 'test-person',
                    properties: expect.objectContaining({
                        invitation_id: String(invitation.result?.requestState).slice('mcp-interview:'.length),
                        interview_recruitment_reason: 'invited',
                        interview_recruitment_url_supported: true,
                    }),
                })
            )

            const resumed = await call(dispatcher, continuation(invitation.result?.requestState, answer))
            expect(resumed.result).toMatchObject({ resultType: 'complete', ...toolResult })
            expect(executeTool).toHaveBeenCalledTimes(1)
            expect(captureRecruitment).toHaveBeenCalledWith(
                expect.objectContaining({
                    event: 'mcp interview invitation responded',
                    properties: expect.objectContaining({ response: answer.action }),
                })
            )
            const [key, record] = [...storage.entries.entries()].find(([key]) => key.endsWith(':response'))!
            expect(record.expires).toBeUndefined()
            expect(JSON.parse(record.value)).toMatchObject({
                distinct_id: 'test-person',
                response: answer.action === 'decline' ? 'do_not_ask_again' : 'booking_link_accepted',
            })

            vi.useFakeTimers()
            vi.setSystemTime(Date.now() + 365 * 24 * 60 * 60 * 1000)
            const reconnected = new McpDispatcher({} as ToolCatalog, storage.redis)
            state.interviewRecruitmentConfig = resolveInterviewRecruitmentConfig('other-study', {
                message: 'Another interview',
                booking_url: 'https://example.com/other',
                min_completed_tool_calls: 0,
                min_session_age_seconds: 0,
            })
            vi.mocked(storage.redis.set).mockClear()
            vi.mocked(storage.redis.eval).mockClear()
            expect((await call(reconnected, callParams(), { ...props, userHash: 'new-token' })).result).toMatchObject(
                toolResult
            )
            expect(storage.redis.set).not.toHaveBeenCalled()
            expect(storage.redis.eval).not.toHaveBeenCalled()
            expect(state.interviewRecruitmentDiagnostics?.reason).toBe('suppressed')
            storage.entries.delete(key)
            expect((await call(reconnected)).result?.resultType).toBe('input_required')
        }
    )

    it('lets cancellation continue and asks again after the cooldown', async () => {
        vi.useFakeTimers()
        const invitation = await call(dispatcher)
        await call(dispatcher, continuation(invitation.result?.requestState, { action: 'cancel' }))
        expect(captureRecruitment).toHaveBeenCalledWith(
            expect.objectContaining({
                event: 'mcp interview invitation responded',
                properties: expect.objectContaining({ response: 'cancel' }),
            })
        )
        state.interviewRecruitmentConfig = resolveInterviewRecruitmentConfig('other-study', {
            message: 'Another interview',
            booking_url: 'https://example.com/other',
            min_completed_tool_calls: 0,
            min_session_age_seconds: 0,
        })
        expect((await call(dispatcher)).result).toMatchObject(toolResult)
        vi.setSystemTime(Date.now() + 7 * 24 * 60 * 60 * 1000)
        expect((await call(dispatcher)).result?.resultType).toBe('input_required')
    })

    it.each([
        [{}, false],
        [{ elicitation: {} }, true],
        [{ elicitation: { form: {} } }, true],
        [{ elicitation: false }, false],
    ] as const)('skips clients without URL support: %j', async (capabilities, formSupported) => {
        expect((await call(dispatcher, callParams(capabilities))).result).toMatchObject(toolResult)
        expect(state.interviewRecruitmentDiagnostics).toMatchObject({
            reason: 'url_unsupported',
            urlSupported: false,
            formSupported,
        })
        expect(storage.entries.size).toBe(0)
    })

    it.each(['disabled', 'missing', 'impersonated', 'suppressed', 'invalid-payload'])(
        'skips recruitment when %s',
        async (condition) => {
            if (condition === 'disabled' || condition === 'missing') {
                state.interviewRecruitmentConfig = resolveInterviewRecruitmentConfig(
                    condition === 'disabled' ? false : undefined,
                    {}
                )
            }
            if (condition === 'invalid-payload') {
                state.interviewRecruitmentConfig = undefined
            }
            state.isImpersonated = condition === 'impersonated'
            state.suppressAnalytics = condition === 'suppressed'
            expect((await call(dispatcher)).result).toMatchObject(toolResult)
            expect(storage.entries.size).toBe(0)
        }
    )

    it.each([
        ['exec', 'scout-trial-get'],
        ['direct', 'scout-trial-get'],
        ['exec', 'scout-rubric-get'],
        ['direct', 'scout-rubric-get'],
    ])('excludes private %s calls to %s from invitations, progress, and analytics', async (mode, toolName) => {
        state.allTools.push({ name: toolName } as (typeof state.allTools)[number])
        const params = callParams()
        if (mode === 'exec') {
            params.arguments = { command: `call ${toolName} {}` }
        } else {
            params.name = toolName
            params.arguments = {}
        }
        expect((await call(dispatcher, params)).result).toMatchObject(toolResult)
        expect(storage.entries.size).toBe(0)
        expect(captureRecruitment).not.toHaveBeenCalled()
    })

    it('waits for three completed product calls and two minutes in the same conversation', async () => {
        vi.useFakeTimers()
        state.interviewRecruitmentConfig = resolveInterviewRecruitmentConfig(true, {
            message: 'Synthetic MCP interview',
            booking_url: 'https://example.com/book',
        })
        expect((await call(dispatcher)).result).toMatchObject(toolResult)
        expect(state.interviewRecruitmentDiagnostics).toMatchObject({
            reason: 'insufficient_tool_calls',
            completedCalls: 0,
            sessionAgeSeconds: 0,
        })
        expect((await call(dispatcher)).result).toMatchObject(toolResult)
        expect((await call(dispatcher)).result).toMatchObject(toolResult)
        expect((await call(dispatcher)).result).toMatchObject(toolResult)
        expect(state.interviewRecruitmentDiagnostics).toMatchObject({
            reason: 'session_too_young',
            completedCalls: 3,
            sessionAgeSeconds: 0,
        })
        vi.advanceTimersByTime(120_000)
        expect((await call(dispatcher)).result?.resultType).toBe('input_required')
        expect(state.interviewRecruitmentDiagnostics).toMatchObject({
            reason: 'invited',
            completedCalls: 4,
            sessionAgeSeconds: 120,
        })
        expect(executeTool).toHaveBeenCalledTimes(4)
    })

    it.each(['failed', 'search', 'learn', 'skill', 'docs'])(
        'does not count %s calls toward the warm-up',
        async (kind) => {
            vi.useFakeTimers()
            state.interviewRecruitmentConfig = resolveInterviewRecruitmentConfig(true, {
                message: 'Synthetic MCP interview',
                booking_url: 'https://example.com/book',
            })
            const params = callParams()
            params.arguments = {
                command: {
                    failed: 'call project-get {}',
                    search: 'search project',
                    learn: 'learn -s project',
                    skill: 'call skill-get {}',
                    docs: 'call docs-search {}',
                }[kind],
            }
            for (let i = 0; i < 3; i++) {
                if (kind === 'failed') {
                    executeTool.mockResolvedValueOnce({ ...toolResult, isError: true })
                }
                expect((await call(dispatcher, params)).result?.resultType).toBe('complete')
            }
            vi.advanceTimersByTime(120_000)
            expect((await call(dispatcher)).result).toMatchObject(toolResult)
            expect((await call(dispatcher)).result).toMatchObject(toolResult)
            vi.advanceTimersByTime(120_000)
            expect((await call(dispatcher)).result).toMatchObject(toolResult)
            expect((await call(dispatcher)).result?.resultType).toBe('input_required')
        }
    )

    it('does not count a replay of the same completed RPC twice', async () => {
        vi.useFakeTimers()
        state.interviewRecruitmentConfig = resolveInterviewRecruitmentConfig(true, {
            message: 'Synthetic MCP interview',
            booking_url: 'https://example.com/book',
        })
        for (let i = 0; i < 3; i++) {
            expect((await call(dispatcher, callParams(), props, 10)).result).toMatchObject(toolResult)
        }
        vi.advanceTimersByTime(120_000)
        expect((await call(dispatcher, callParams(), props, 11)).result).toMatchObject(toolResult)
        expect((await call(dispatcher, callParams(), props, 12)).result).toMatchObject(toolResult)
        expect((await call(dispatcher, callParams(), props, 13)).result?.resultType).toBe('input_required')
    })

    it.each(['missing conversation', 'different conversation', 'different client', 'different person'])(
        'does not reuse warm-up progress for a %s',
        async (change) => {
            vi.useFakeTimers()
            state.interviewRecruitmentConfig = resolveInterviewRecruitmentConfig(true, {
                message: 'Synthetic MCP interview',
                booking_url: 'https://example.com/book',
            })
            for (let i = 0; i < 3; i++) {
                await call(dispatcher)
            }
            vi.advanceTimersByTime(120_000)
            if (change === 'missing conversation') {
                state.requestContext.mcpConversationId = undefined
            }
            if (change === 'different conversation') {
                state.requestContext.mcpConversationId = 'conversation-b'
            }
            if (change === 'different client') {
                state.requestContext.mcpClientName = 'another-client'
            }
            if (change === 'different person') {
                state.distinctId = 'another-person'
            }
            expect((await call(dispatcher)).result).toMatchObject(toolResult)
        }
    )

    it('reserves only one invitation across simultaneous campaigns and server instances', async () => {
        const otherState = {
            ...state,
            interviewRecruitmentConfig: resolveInterviewRecruitmentConfig('other-study', {
                message: 'Another interview',
                booking_url: 'https://example.com/other',
                min_completed_tool_calls: 0,
                min_session_age_seconds: 0,
            }),
        }
        resolveState.mockResolvedValueOnce(state).mockResolvedValueOnce(otherState)
        const other = new McpDispatcher({} as ToolCatalog, storage.redis)
        const results = await Promise.all([call(dispatcher), call(other)])
        expect(results.filter((r) => r.result?.resultType === 'input_required')).toHaveLength(1)
        expect(executeTool).toHaveBeenCalledTimes(1)
        expect(
            captureRecruitment.mock.calls.filter(([event]) => event.event === 'mcp interview invitation sent')
        ).toHaveLength(1)
    })

    it('does not prompt legacy clients', async () => {
        const legacy = new Request('https://mcp.test/mcp', {
            method: 'POST',
            body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'exec' } }),
        })
        const result = (await (await dispatcher.handleRequest(legacy, props)).json()) as { result: unknown }
        expect(result.result).toEqual(toolResult)
        expect(storage.entries.size).toBe(0)
        expect(state.interviewRecruitmentDiagnostics).toMatchObject({
            reason: 'legacy_protocol',
            urlSupported: null,
            formSupported: null,
        })
    })

    it.each(['token', 'person', 'arguments', 'project', 'organization', 'expired', 'replayed', 'invalid-answer'])(
        'rejects a %s continuation without executing the tool',
        async (change) => {
            vi.useFakeTimers()
            const invitation = await call(dispatcher)
            const resumed = continuation(invitation.result?.requestState, {
                action: 'accept',
            })
            let continuationProps = props
            if (change === 'token') {
                continuationProps = { ...props, userHash: 'another-token' }
            } else if (change === 'person') {
                state.distinctId = 'another-person'
            } else if (change === 'arguments') {
                resumed.arguments = { command: 'call project-delete {}' }
            } else if (change === 'project') {
                vi.mocked(state.context.stateManager.getProjectId).mockResolvedValue('2')
            } else if (change === 'organization') {
                vi.mocked(state.context.stateManager.getOrgID).mockResolvedValue('org-2')
            } else if (change === 'expired') {
                vi.setSystemTime(Date.now() + 10 * 60 * 1000)
            } else if (change === 'replayed') {
                await call(dispatcher, resumed)
                executeTool.mockClear()
            } else {
                resumed.inputResponses = { 'mcp-interview': { action: 'unknown' } }
            }
            const rejected = await call(dispatcher, resumed, continuationProps)
            expect(rejected.error?.code).toBe(-32602)
            if (change === 'replayed') {
                expect(rejected.error?.message).toContain('already consumed')
            }
            if (change === 'expired') {
                expect(rejected.error?.message).toContain('Check whether the original tool completed')
            }
            expect(executeTool).not.toHaveBeenCalled()
        }
    )

    it('processes a displayed invitation after its flag has been disabled', async () => {
        const invitation = await call(dispatcher)
        state.interviewRecruitmentConfig = undefined
        expect(
            (await call(dispatcher, continuation(invitation.result?.requestState, { action: 'decline' }))).result
        ).toMatchObject(toolResult)
        expect(
            JSON.parse([...storage.entries.entries()].find(([key]) => key.endsWith(':response'))![1].value).response
        ).toBe('do_not_ask_again')
    })

    it('skips the invitation if Redis fails, but retries a response write before executing the tool', async () => {
        vi.mocked(storage.redis.eval).mockRejectedValueOnce(new Error('unavailable'))
        expect((await call(dispatcher)).result).toMatchObject(toolResult)
        expect(state.interviewRecruitmentDiagnostics?.reason).toBe('redis_error')
        executeTool.mockClear()
        const invitation = await call(dispatcher)
        const resumed = continuation(invitation.result?.requestState, { action: 'decline' })
        vi.mocked(storage.redis.eval).mockRejectedValueOnce(new Error('unavailable'))
        expect((await call(dispatcher, resumed)).error?.code).toBe(-32603)
        expect(executeTool).not.toHaveBeenCalled()
        expect((await call(dispatcher, resumed)).result).toMatchObject(toolResult)
    })

    it('keeps original campaign attribution after a flag change and deduplicates actual link opens', async () => {
        vi.useFakeTimers()
        state.interviewRecruitmentConfig = resolveInterviewRecruitmentConfig('first-study', {
            message: 'First interview',
            booking_url: 'https://example.com/first',
            min_completed_tool_calls: 0,
            min_session_age_seconds: 0,
        })
        const invitation = await call(dispatcher)
        const inputs = invitation.result?.inputRequests as Record<string, { params: { url: string } }>
        const url = inputs['mcp-interview']!.params.url
        state.interviewRecruitmentConfig = resolveInterviewRecruitmentConfig('second-study', {
            message: 'Second interview',
            booking_url: 'https://example.com/second',
        })
        const app = new Hono()
        registerPublicRoutes(app, storage.redis, { shuttingDown: false })
        expect(captureRecruitment.mock.calls.map(([event]) => event.event)).toEqual(['mcp interview invitation sent'])
        expect((await app.request(url, { method: 'HEAD' })).status).toBe(405)
        expect(captureRecruitment).toHaveBeenCalledTimes(1)
        const redirects = await Promise.all([app.request(url), app.request(url)])
        for (const redirect of redirects) {
            expect(redirect.status).toBe(302)
            expect(redirect.headers.get('Location')).toBe('https://example.com/first')
            expect(redirect.headers.get('Referrer-Policy')).toBe('no-referrer')
            expect(redirect.headers.get('Cache-Control')).toBe('no-store')
        }
        expect(captureRecruitment.mock.calls.map(([event]) => event.event)).toEqual([
            'mcp interview invitation sent',
            'mcp interview booking link opened',
        ])
        await call(dispatcher, continuation(invitation.result?.requestState, { action: 'accept' }))
        expect(captureRecruitment).toHaveBeenLastCalledWith(
            expect.objectContaining({
                event: 'mcp interview invitation responded',
                properties: expect.objectContaining({ response: 'accept' }),
            })
        )
        vi.advanceTimersByTime(7 * 24 * 60 * 60 * 1000)
        expect((await app.request(url)).status).toBe(404)
        expect((await app.request('/interview/unknown?url=https://example.com')).status).toBe(404)
        expect(captureRecruitment).toHaveBeenCalledTimes(3)
        for (const [event] of captureRecruitment.mock.calls) {
            expect(event.properties.campaign_id).toBe('first-study')
        }
        const responseRecord = [...storage.entries.entries()].find(([key]) => key.endsWith(':response'))![1]
        expect(JSON.parse(responseRecord.value).campaign_id).toBe('first-study')
    })

    it('continues the booking redirect and original tool when analytics capture fails', async () => {
        captureRecruitment.mockImplementation(() => {
            throw new Error('capture unavailable')
        })
        try {
            const invitation = await call(dispatcher)
            const app = new Hono()
            registerPublicRoutes(app, storage.redis, { shuttingDown: false })
            const inputs = invitation.result?.inputRequests as Record<string, { params: { url: string } }>
            expect((await app.request(inputs['mcp-interview']!.params.url)).status).toBe(302)
            expect(
                (await call(dispatcher, continuation(invitation.result?.requestState, { action: 'accept' }))).result
            ).toMatchObject(toolResult)
        } finally {
            captureRecruitment.mockReset()
        }
    })

    it('completes the URL round trip with the official MCP client', async () => {
        const client = new Client(
            { name: 'recruitment-test', version: '1.0.0' },
            { capabilities: { elicitation: { url: {} } }, versionNegotiation: { mode: { pin: '2026-07-28' } } }
        )
        const onInvitation = vi.fn(async () => ({ action: 'accept' as const }))
        client.setRequestHandler('elicitation/create', onInvitation)
        const transport = new StreamableHTTPClientTransport(new URL('https://mcp.test/mcp'), {
            fetch: async (input, init) => dispatcher.handleRequest(new Request(input, init), props),
        })
        try {
            await client.connect(transport)
            const result = await client.callTool({ name: 'exec', arguments: { command: 'call project-get {}' } })
            expect(result).toMatchObject(toolResult)
            expect(onInvitation).toHaveBeenCalledTimes(1)
            expect(executeTool).toHaveBeenCalledTimes(1)
        } finally {
            await client.close()
        }
    })
})
