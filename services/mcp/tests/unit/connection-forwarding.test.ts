import { afterEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { ApiClient } from '@/api/client'
import { ForwardingApiClient } from '@/lib/connection-forwarding'
import { ExecCommandError, PostHogApiError } from '@/lib/errors'
import { StateManager } from '@/lib/StateManager'
import executeSqlTool from '@/tools/posthogAiTools/executeSql'
import { createConnectionCallTool } from '@/tools/posthogConnections/call'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const TARGET = {
    project_id: 4242,
    project_name: 'EU Team',
    organization_id: 'org-uuid',
    organization_name: 'EU Org',
    region: 'EU',
    base_url: 'https://eu.posthog.com',
}

const FORWARD_PATH = '/api/projects/7/posthog_connections/99/forward/'
const TARGET_PATH = '/api/projects/7/posthog_connections/99/target/'

/** A catalogued tool carrying `requires_ai_consent`. */
const AI_CONSENT_TOOL = 'web-analytics-path-cleaning-suggestions-generate'

/** A local client whose only job is to answer the two connection endpoints. */
function createLocalApi(request: ReturnType<typeof vi.fn>): ApiClient {
    const api = new ApiClient({ apiToken: 'local-token', baseUrl: 'https://us.posthog.com' })
    api.request = request as unknown as ApiClient['request']
    return api
}

function createContext(request: ReturnType<typeof vi.fn>): Context {
    return {
        api: createLocalApi(request),
        stateManager: { getProjectId: vi.fn().mockResolvedValue('7') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'distinct-id',
        trackEvent: async () => {},
    }
}

/** Routes every connection endpoint; `forward` echoes back what the target "returned". */
function createRequestMock(forwardResponse: { status: number; data: unknown }): ReturnType<typeof vi.fn> {
    return vi.fn(async (opts: { method: string; path: string; body?: Record<string, unknown> }) => {
        if (opts.path === TARGET_PATH) {
            return TARGET
        }
        if (opts.path === FORWARD_PATH) {
            return forwardResponse
        }
        throw new Error(`unexpected request to ${opts.path}`)
    })
}

/** Stand-in for a real registry tool: makes one API call the way generated tools do. */
function fakeTool(name: string): ToolBase<ZodObjectAny> {
    return {
        name,
        schema: z.object({ query: z.string() }),
        handler: async (context: Context, params: any) =>
            await context.api.request({
                method: 'POST',
                path: `/api/projects/${await context.stateManager.getProjectId()}/query/`,
                body: { query: params.query },
            }),
    } as ToolBase<ZodObjectAny>
}

describe('posthog connection forwarding', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
        // The AI-consent cases spy on StateManager's prototype, which outlives the test without this.
        vi.restoreAllMocks()
    })

    describe('ForwardingApiClient', () => {
        it('rewrites a request into the forward endpoint and unwraps the target response', async () => {
            const request = createRequestMock({ status: 200, data: { results: [[1]] } })
            const forwarding = new ForwardingApiClient(createLocalApi(request), {
                connectionId: '99',
                localProjectId: '7',
                target: TARGET,
            })

            const result = await forwarding.request({
                method: 'GET',
                path: '/api/projects/4242/insights/',
                query: { limit: 5 },
            })

            expect(request).toHaveBeenCalledWith({
                method: 'POST',
                path: FORWARD_PATH,
                body: { method: 'GET', path: 'api/projects/4242/insights/', query: { limit: '5' } },
            })
            expect(result).toEqual({ results: [[1]] })
        })

        it('sends a write body as `data`', async () => {
            const request = createRequestMock({ status: 201, data: { id: 'abc' } })
            const forwarding = new ForwardingApiClient(createLocalApi(request), {
                connectionId: '99',
                localProjectId: '7',
                target: TARGET,
            })

            await forwarding.request({ method: 'POST', path: '/api/projects/4242/query/', body: { query: 'select 1' } })

            expect(request.mock.calls[0]![0].body).toEqual({
                method: 'POST',
                path: 'api/projects/4242/query/',
                data: { query: 'select 1' },
            })
        })

        it('surfaces a status the target returned as a thrown API error', async () => {
            // The forward endpoint answers 200 whatever the target said. Without re-raising it here,
            // a tool reads the error envelope as a successful result and reports made-up data.
            const request = createRequestMock({ status: 403, data: { detail: 'Scope missing' } })
            const forwarding = new ForwardingApiClient(createLocalApi(request), {
                connectionId: '99',
                localProjectId: '7',
                target: TARGET,
            })

            const error: any = await forwarding
                .request({ method: 'GET', path: '/api/projects/4242/insights/' })
                .catch((e) => e)

            expect(error).toBeInstanceOf(PostHogApiError)
            expect(error.status).toBe(403)
            expect(error.body).toContain('Scope missing')
        })

        it('turns a refusal from this side into the request’s own failure', async () => {
            // The gateway refusing (connection revoked, scopes too narrow) is the answer to the
            // request the tool made — it must not escape as an unrelated exception shape.
            const request = vi.fn().mockRejectedValue(
                new PostHogApiError({
                    status: 403,
                    statusText: 'Forbidden',
                    body: '{"detail":"You can only use a PostHog connection you created."}',
                    url: FORWARD_PATH,
                    method: 'POST',
                })
            )
            const forwarding = new ForwardingApiClient(createLocalApi(request), {
                connectionId: '99',
                localProjectId: '7',
                target: TARGET,
            })

            const error: any = await forwarding
                .request({ method: 'GET', path: '/api/projects/4242/insights/' })
                .catch((e) => e)

            expect(error).toBeInstanceOf(PostHogApiError)
            expect(error.status).toBe(403)
            expect(error.body).toContain('only use a PostHog connection you created')
        })
    })

    describe('posthog-connection-call', () => {
        it('runs the named tool against the connected project id, not the local one', async () => {
            // This is the promise the tool makes: the agent passes no project id and never resolves
            // one. If the forwarded context leaked the local id, every call would hit the wrong project.
            const request = createRequestMock({ status: 200, data: { results: [[1]] } })
            const tool = createConnectionCallTool((name) => (name === 'execute-sql' ? fakeTool(name) : undefined))

            const result: any = await tool.handler(createContext(request), {
                connection_id: '99',
                tool: 'execute-sql',
                arguments: { query: 'select 1 from events limit 5' },
            })

            const forwardCall = request.mock.calls.find(([opts]: any[]) => opts.path === FORWARD_PATH)
            expect(forwardCall![0].body).toEqual({
                method: 'POST',
                path: 'api/projects/4242/query/',
                data: { query: 'select 1 from events limit 5' },
            })
            expect(result.result).toEqual({ results: [[1]] })
            expect(result.ran_in).toMatchObject({ project_id: 4242, region: 'EU' })
        })

        it.each([
            ['an unknown tool name', 'no-such-tool'],
            ['a connection chained through itself', 'posthog-connection-call'],
            ['the raw forwarder', 'posthog-connection-forward'],
            ['a session-state tool', 'switch-project'],
        ])('refuses %s before contacting the connection', async (_case, toolName) => {
            const request = createRequestMock({ status: 200, data: {} })
            const tool = createConnectionCallTool((name) => (name === 'execute-sql' ? fakeTool(name) : undefined))

            const error = await tool
                .handler(createContext(request), { connection_id: '99', tool: toolName, arguments: {} })
                .catch((e) => e)

            expect(error).toBeInstanceOf(ExecCommandError)
            expect(request).not.toHaveBeenCalledWith(expect.objectContaining({ path: FORWARD_PATH }))
        })

        it('runs a tool that builds its own request through the connection, not against the target', async () => {
            // `execute-sql` reaches the API through `invokeMcpTool` rather than a generated handler.
            // Whatever route it takes has to be the client's, or it sends the caller's own bearer
            // token straight to the connected project's server and skips `forward/` entirely.
            const globalFetch = vi.fn()
            vi.stubGlobal('fetch', globalFetch)
            const request = createRequestMock({ status: 200, data: { success: true, content: 'rows' } })
            const tool = createConnectionCallTool((name) => (name === 'execute-sql' ? executeSqlTool() : undefined))

            const result: any = await tool.handler(createContext(request), {
                connection_id: '99',
                tool: 'execute-sql',
                arguments: { query: 'select 1' },
            })

            const forwardCall = request.mock.calls.find(([opts]: any[]) => opts.path === FORWARD_PATH)
            expect(forwardCall![0].body).toMatchObject({
                method: 'POST',
                path: 'api/environments/4242/mcp_tools/execute_sql/',
            })
            expect(globalFetch).not.toHaveBeenCalled()
            expect(result.result).toBe('rows')
        })

        it.each([
            ['the target has not approved it', false],
            ['the target’s approval cannot be read', undefined],
        ])('refuses an AI-consuming tool when %s', async (_case, consent) => {
            // AI consent is filtered per session locally, but a tool named here comes from the
            // registry, and it is the *other* organization's approval that governs. The API gates
            // these endpoints on a feature flag and scopes only, so nothing downstream would stop it.
            const request = createRequestMock({ status: 200, data: {} })
            const tool = createConnectionCallTool(() => fakeTool(AI_CONSENT_TOOL))
            const context = createContext(request)
            vi.spyOn(StateManager.prototype, 'getAiConsentGiven').mockResolvedValue(consent)

            const error: any = await tool
                .handler(context, { connection_id: '99', tool: AI_CONSENT_TOOL, arguments: { query: 'x' } })
                .catch((e) => e)

            expect(error).toBeInstanceOf(ExecCommandError)
            expect(error.message).toContain('has not approved AI data processing')
            expect(request).not.toHaveBeenCalledWith(expect.objectContaining({ path: FORWARD_PATH }))
        })

        it('runs an AI-consuming tool once the target has approved it', async () => {
            // Guards the other direction: a gate that refused regardless would satisfy the cases above.
            const request = createRequestMock({ status: 200, data: { ok: true } })
            const tool = createConnectionCallTool(() => fakeTool(AI_CONSENT_TOOL))
            vi.spyOn(StateManager.prototype, 'getAiConsentGiven').mockResolvedValue(true)

            const result: any = await tool.handler(createContext(request), {
                connection_id: '99',
                tool: AI_CONSENT_TOOL,
                arguments: { query: 'x' },
            })

            expect(result.result).toEqual({ ok: true })
        })

        it('rejects arguments the target tool would not accept, without contacting the connection', async () => {
            // Validating up front keeps a malformed call from burning a cross-region round trip and
            // coming back as an opaque 400 from the other project.
            const request = createRequestMock({ status: 200, data: {} })
            const tool = createConnectionCallTool(() => fakeTool('execute-sql'))

            const error: any = await tool
                .handler(createContext(request), { connection_id: '99', tool: 'execute-sql', arguments: { q: 1 } })
                .catch((e) => e)

            expect(error).toBeInstanceOf(ExecCommandError)
            expect(error.message).toContain('query')
            expect(request).not.toHaveBeenCalled()
        })
    })
})
