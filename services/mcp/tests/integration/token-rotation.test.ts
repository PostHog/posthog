import { beforeEach, describe, expect, it, vi } from 'vitest'

// Integration test for OAuth token rotation on warm Durable Objects.
//
// The PostHog MCP server lives behind Cloudflare DOs keyed by `mcp-session-id`.
// When the upstream OAuth token rotates, the same session id keeps landing on
// the same warm DO instance — partyserver only updates its private `#_props`
// and skips `onStart`, so neither `this.props` nor the cached `ApiClient`
// that tool handlers captured during `init()` see the new token unless we
// rotate them explicitly.
//
// These tests pin the load-bearing invariant:
//   *The ApiClient reference captured during init() must see the rotated
//    token after every subsequent setName() call for the same session.*
//
// If a future refactor reintroduces `this._api = new ApiClient(...)` on
// rotation (instead of mutating in place), these tests will fail — exactly
// as the production bug would.

const ApiClientCtor = vi.fn()

vi.mock('@/api/client', () => ({
    ApiClient: class {
        config: { apiToken: string; baseUrl: string; [k: string]: any }
        baseUrl: string
        constructor(config: any) {
            this.config = config
            this.baseUrl = config.baseUrl
            ApiClientCtor(config)
        }
    },
}))

// Mirrors what a real tool handler does after `getContext()`: it captures the
// ApiClient once, then reads `.config.apiToken` on every downstream request.
// If in-place rotation ever regresses to instance replacement, this helper
// returns stale and the tests fail.
function readTokenFromCapturedApi(api: { config: { apiToken: string } }): string {
    return api.config.apiToken
}

vi.mock('agents/mcp', () => ({
    McpAgent: class {
        async setName(): Promise<void> {
            // partyserver updates its private #_props here on warm DOs and
            // returns early without touching `this.props` or re-running
            // onStart — this is precisely the gap the subclass override
            // compensates for.
        }
        async updateProps(props: unknown): Promise<void> {
            await (this as any).ctx.storage.put('props', props ?? {})
            ;(this as any).props = props
        }
    },
}))

vi.mock('@modelcontextprotocol/sdk/server/mcp.js', () => ({
    McpServer: class {},
}))

vi.mock('@modelcontextprotocol/ext-apps/server', () => ({
    RESOURCE_URI_META_KEY: 'resource-uri',
}))

vi.mock('@shared/guidelines.md', () => ({
    default: '',
}))

import { MCP } from '@/mcp'

function buildMcp(): MCP {
    const mcp = Object.create(MCP.prototype) as MCP
    const storage = new Map<string, unknown>()
    ;(mcp as any).ctx = {
        storage: {
            put: async (key: string, value: unknown) => {
                storage.set(key, value)
            },
            get: async (key: string) => storage.get(key),
        },
    }
    ;(mcp as any).getBaseUrl = async () => 'https://us.posthog.com'
    ;(mcp as any).resolveClientInfo = async () => {}
    return mcp
}

type TestProps = { userHash: string; apiToken: string; clientUserAgent: string }

function propsFor(apiToken: string): TestProps {
    return {
        userHash: 'user-hash',
        apiToken,
        clientUserAgent: 'test-agent',
    }
}

const SESSION_NAME = 'streamable-http:session-abc'

describe('OAuth token rotation on warm DOs — integration', () => {
    beforeEach(() => {
        ApiClientCtor.mockClear()
    })

    it('captured context.api reference sees each rotated token without a rebuild', async () => {
        const mcp = buildMcp()

        // Cold start: agents SDK runs onStart(props) → updateProps(props).
        await (mcp as any).updateProps(propsFor('token-A'))

        // init()'s getContext() calls api() and hands the resulting ApiClient
        // reference to every tool registration. Tools hold this reference for
        // the lifetime of the DO.
        const capturedApi = await mcp.api()

        // Cold start: first "tool call" fires with token-A.
        expect(readTokenFromCapturedApi(capturedApi)).toBe('token-A')

        // Warm request 1: OAuth token has rotated to token-B. The SDK calls
        // setName(sessionName, propsB) on the same DO — no onStart, no
        // updateProps on the subclass-visible state.
        await (mcp as any).setName(SESSION_NAME, propsFor('token-B'))
        expect(readTokenFromCapturedApi(capturedApi)).toBe('token-B')

        // Warm request 2: another rotation to token-C.
        await (mcp as any).setName(SESSION_NAME, propsFor('token-C'))
        expect(readTokenFromCapturedApi(capturedApi)).toBe('token-C')

        // Critical: only one ApiClient was ever constructed. All rotations
        // mutated `.config.apiToken` in place — if we had replaced the
        // instance, `capturedApi` would still point at the original.
        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
    })

    it('is resilient across many rotations (OAuth refresh loop)', async () => {
        const mcp = buildMcp()
        await (mcp as any).updateProps(propsFor('token-initial'))
        const capturedApi = await mcp.api()

        const rotations = ['token-1', 'token-2', 'token-3', 'token-4', 'token-5']
        for (const token of rotations) {
            await (mcp as any).setName(SESSION_NAME, propsFor(token))
            expect(readTokenFromCapturedApi(capturedApi)).toBe(token)
        }

        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
    })

    it('hibernation wake via updateProps also rotates the captured reference', async () => {
        // When a DO wakes from hibernation with fresh props, the agents SDK
        // re-runs onStart → updateProps. The same in-place rotation keeps
        // any references that survived the wake pointing at the new token.
        const mcp = buildMcp()
        await (mcp as any).updateProps(propsFor('token-A'))
        const capturedApi = await mcp.api()
        expect(readTokenFromCapturedApi(capturedApi)).toBe('token-A')

        // DO wakes with a rotated token — updateProps path instead of setName.
        await (mcp as any).updateProps(propsFor('token-B'))

        expect(readTokenFromCapturedApi(capturedApi)).toBe('token-B')
        expect(ApiClientCtor).toHaveBeenCalledTimes(1)
    })

    it('setName before any api() call does not prematurely construct an ApiClient', async () => {
        // Sanity check on the rotation primitive: with no cached client yet,
        // rotateCachedApiToken is a no-op (nothing to mutate). Construction
        // is strictly lazy and happens on the first api() call.
        const mcp = buildMcp()
        await (mcp as any).updateProps(propsFor('token-A'))

        await (mcp as any).setName(SESSION_NAME, propsFor('token-B'))
        expect(ApiClientCtor).not.toHaveBeenCalled()
    })

    it('regression: tool handlers that captured context.api during init() never see a stale token', async () => {
        // Reproduces the production bug this fix solves. Before the setName
        // override, a warm DO receiving a rotated token would leave the
        // captured ApiClient's token unchanged, so every subsequent tool
        // call failed with "Invalid access token" until the DO hibernated
        // and cold-started.
        const mcp = buildMcp()
        await (mcp as any).updateProps(propsFor('token-before'))

        // Simulate init() → getToolsFromContext() → each tool captures the
        // same `context.api` reference into its closure.
        const capturedApi = await mcp.api()
        const toolHandler = async (): Promise<string> => readTokenFromCapturedApi(capturedApi)

        // Warm request arrives with a rotated token.
        await (mcp as any).setName(SESSION_NAME, propsFor('token-after'))

        // The tool handler — which never re-reads `context.api` — must now
        // return the new token. If this ever regresses to 'token-before',
        // the production bug is back.
        expect(await toolHandler()).toBe('token-after')
    })
})
