import { env, runInDurableObject } from 'cloudflare:test'
import { describe, expect, it } from 'vitest'

import type { MCP } from '@/mcp'

// DO-level integration test for OAuth token rotation against the real Workers
// runtime. The production bug: Cloudflare routes the same `mcp-session-id` to
// the same warm DO, and partyserver's `setName` short-circuits on warm DOs,
// updating only its private `#_props` and returning early without re-running
// `onStart`. That leaves the cached `ApiClient` — captured during `init()` and
// handed to every tool handler via `context.api` — pointing at a stale token.
//
// These tests exercise the `updateProps` override (which the agents SDK calls
// from `onStart` on every cold start and hibernation wake) against the real
// `agents/mcp` McpAgent + `partyserver` Server base classes via
// `runInDurableObject`. The `setName` override delegates to the same
// `rotateCachedApiToken` primitive, so warm-setName coverage is handled by the
// unit tests in `tests/unit/mcp-api-caching.test.ts` — attempting to exercise
// it end-to-end here would require full cold-start `init()` to complete, which
// pulls in every PostHog endpoint + context-mill + MCPCat and is better
// covered at the HTTP layer in a future test.

const propsFor = (apiToken: string): { userHash: string; apiToken: string; clientUserAgent: string } => ({
    userHash: 'user-hash',
    apiToken,
    clientUserAgent: 'test-agent',
})

// Mirrors what a tool handler does after capturing `context.api` in its
// closure: read `.config.apiToken` on every downstream request. If in-place
// rotation ever regresses to instance replacement, this returns stale.
function readTokenFromCapturedApi(api: { config: { apiToken: string } }): string {
    return api.config.apiToken
}

describe('MCP token rotation inside the real Workers runtime', () => {
    it('updateProps rotates the cached ApiClient token in place (hibernation wake path)', async () => {
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-updateprops'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            // Cold path: updateProps persists props to storage and assigns this.props.
            // rotateCachedApiToken is a no-op since there's no cached _api yet.
            await mcp.updateProps(propsFor('token-A'))
            expect(mcp.props).toEqual(propsFor('token-A'))

            // Construct the ApiClient lazily — this is the reference that tool
            // handlers capture via `context.api` during init().
            const capturedApi = await mcp.api()
            expect(readTokenFromCapturedApi(capturedApi)).toBe('token-A')

            // Hibernation-wake path: agents SDK calls updateProps(propsB) and
            // our override rotates the cached token synchronously (before the
            // storage write) so any tool handler reading config.apiToken
            // observes the new token without waiting.
            await mcp.updateProps(propsFor('token-B'))
            expect(readTokenFromCapturedApi(capturedApi)).toBe('token-B')
            expect(mcp.props).toEqual(propsFor('token-B'))

            // Storage persisted the new props (partyserver hydrates from here
            // after the DO sleeps and wakes).
            const storedProps = await (mcp as unknown as { ctx: DurableObjectState }).ctx.storage.get('props')
            expect(storedProps).toEqual(propsFor('token-B'))
        })
    })

    it('is resilient across many updateProps rotations (OAuth refresh loop)', async () => {
        // Repeated hibernation wakes with fresh tokens. The captured ApiClient
        // reference must track every rotation without being rebuilt.
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-many-rotations'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            await mcp.updateProps(propsFor('token-initial'))
            const capturedApi = await mcp.api()

            const rotations = ['token-1', 'token-2', 'token-3', 'token-4', 'token-5']
            for (const token of rotations) {
                await mcp.updateProps(propsFor(token))
                expect(readTokenFromCapturedApi(capturedApi)).toBe(token)
            }

            // Final identity check: the reference is still the instance that
            // `api()` hands out — we never replaced it.
            expect(await mcp.api()).toBe(capturedApi)
        })
    })

    it('regression: a tool-handler-style closure reads the rotated token after warm rotation', async () => {
        // Reproduces the production bug. Before the override, a closure over
        // `context.api` (what every tool handler is) kept returning the stale
        // token on warm DOs until the DO hibernated and cold-started.
        const stub = env.MCP_OBJECT.get(env.MCP_OBJECT.idFromName('session-closure'))

        await runInDurableObject(stub, async (mcp: MCP) => {
            await mcp.updateProps(propsFor('token-before'))
            const capturedApi = await mcp.api()
            const toolHandler = (): string => readTokenFromCapturedApi(capturedApi)

            expect(toolHandler()).toBe('token-before')

            await mcp.updateProps(propsFor('token-after'))

            // The closure — which never re-reads `context.api` — must now see
            // the new token. Regression to instance replacement (or omission
            // of the rotation) flips this to 'token-before'.
            expect(toolHandler()).toBe('token-after')
        })
    })
})
