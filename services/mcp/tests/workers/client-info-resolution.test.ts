import { env, runInDurableObject } from 'cloudflare:test'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { MCP } from '@/mcp'

// DO-level integration tests for MCP client-info resolution. The real worker
// flow sets `mcpClientName` / `mcpClientVersion` / `mcpProtocolVersion` onto
// `ctx.props` at the worker entry point (via `extractClientInfoFromBody` in
// `src/index.ts`) on requests whose body contains a JSON-RPC `initialize`
// message. Subsequent tool-call requests routed to the same warm DO have no
// `initialize` body, so the props for *that* request carry no client-info
// fields — the instance state populated during init() is what every tool
// handler reads.
//
// These tests exercise the whole `init()` flow against the real Workers
// runtime + DO and then simulate a subsequent tool-call request by mutating
// `mcp.props`. The shared workers config (vitest.workers.config.mts) stubs
// outbound PostHog calls, so init completes without real network.

function interceptWaitUntil(mcp: MCP): { flush: () => Promise<void> } {
    const pending: Promise<unknown>[] = []
    const ctx = (mcp as any).ctx
    // Replace — do NOT forward to the original. The real `ctx.waitUntil`
    // keeps the DO alive after the handler returns, which means the promise
    // can access storage *after* `runInDurableObject` has already popped the
    // isolated storage frame. Collecting and flushing ourselves keeps all
    // storage access inside the frame.
    ctx.waitUntil = (p: Promise<unknown>) => {
        pending.push(p)
    }
    return {
        async flush() {
            await Promise.allSettled(pending)
            pending.length = 0
        },
    }
}

const propsWithClientInfo = {
    userHash: 'user-hash-client-info',
    apiToken: 'phx_test_token',
    clientUserAgent: 'test-agent',
    mcpClientName: 'claude-code',
    mcpClientVersion: '1.0.42',
    mcpProtocolVersion: '2024-11-05',
}

const propsWithoutClientInfo = {
    userHash: 'user-hash-client-info',
    apiToken: 'phx_test_token',
    clientUserAgent: 'test-agent',
    // mcpClientName / mcpClientVersion / mcpProtocolVersion intentionally
    // omitted — mirrors a tool-call request whose body isn't `initialize`.
}

describe('MCP client-info resolution inside the real Workers runtime', () => {
    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('init seeds client info from props and a subsequent tool-call request still sees it', async () => {
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-client-info-props'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            const bg = interceptWaitUntil(mcp)
            ;(mcp as any).props = { ...propsWithClientInfo }
            // Pre-seed project cache so init() skips the setDefault path.
            // This test is about client-info resolution, not project resolution.
            await mcp.cache.set('orgId', 'test-org')
            await mcp.cache.set('projectId', 'test-project')

            await mcp.init()

            // Instance fields populated from the initialize request's props.
            expect((mcp as any).mcpClientName).toBe('claude-code')
            expect((mcp as any).mcpClientVersion).toBe('1.0.42')
            expect((mcp as any).mcpProtocolVersion).toBe('2024-11-05')
            expect((mcp as any).clientInfoResolved).toBe(true)

            // The ApiClient constructed during init — the same reference every
            // tool handler captures via `context.api` — carries the client-info
            // fields into its outbound headers.
            const api = await mcp.api()
            expect(api.config.mcpClientName).toBe('claude-code')
            expect(api.config.mcpClientVersion).toBe('1.0.42')
            expect(api.config.mcpProtocolVersion).toBe('2024-11-05')

            // Simulate the next request on the same warm DO: body is
            // `tools/call`, so `extractClientInfoFromBody` returns empty and
            // `requestProperties.mcpClientName` is now absent. A tool handler
            // triggers `resolveClientInfo` via `api()` or `trackEvent()`.
            ;(mcp as any).props = { ...propsWithoutClientInfo }

            await mcp.resolveClientInfo()

            // Memoized — instance state survives across requests in the same
            // DO lifetime, even though the per-request props no longer hold
            // the client info.
            expect((mcp as any).mcpClientName).toBe('claude-code')
            expect((mcp as any).mcpClientVersion).toBe('1.0.42')
            expect((mcp as any).mcpProtocolVersion).toBe('2024-11-05')

            await bg.flush()
        })
    })

    it('init without props falls back to getInitializeRequest on the first post-init call', async () => {
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-client-info-storage'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            const bg = interceptWaitUntil(mcp)
            ;(mcp as any).props = { ...propsWithoutClientInfo }
            await mcp.cache.set('orgId', 'test-org')
            await mcp.cache.set('projectId', 'test-project')

            // During init() the framework hasn't persisted the initialize
            // message yet, so `getInitializeRequest()` returns nothing for
            // every resolveClientInfo attempt that init makes (there are a
            // couple: the explicit top-of-init call and the one inside
            // `api()` → `getContext`).
            const getInitializeRequest = vi
                .spyOn(mcp as unknown as { getInitializeRequest: () => Promise<unknown> }, 'getInitializeRequest')
                .mockResolvedValue(undefined)

            await mcp.init()

            // Init could not resolve — instance state stays unset and the
            // memoization flag stays `false` so a later caller can retry.
            expect((mcp as any).mcpClientName).toBeUndefined()
            expect((mcp as any).mcpClientVersion).toBeUndefined()
            expect((mcp as any).mcpProtocolVersion).toBeUndefined()
            expect((mcp as any).clientInfoResolved).toBe(false)

            // Storage write has now landed (simulated by flipping the mock).
            // A subsequent tool handler triggers `resolveClientInfo` and the
            // fallback succeeds.
            getInitializeRequest.mockResolvedValue({
                params: {
                    clientInfo: { name: 'cursor', version: '0.42.1' },
                    protocolVersion: '2024-11-05',
                },
            })

            await mcp.resolveClientInfo()

            expect((mcp as any).mcpClientName).toBe('cursor')
            expect((mcp as any).mcpClientVersion).toBe('0.42.1')
            expect((mcp as any).mcpProtocolVersion).toBe('2024-11-05')
            expect((mcp as any).clientInfoResolved).toBe(true)

            // Further calls short-circuit on the memoization flag — no
            // additional `getInitializeRequest` invocation.
            const beforeCalls = getInitializeRequest.mock.calls.length
            await mcp.resolveClientInfo()
            expect(getInitializeRequest.mock.calls.length).toBe(beforeCalls)

            await bg.flush()
        })
    })
})
