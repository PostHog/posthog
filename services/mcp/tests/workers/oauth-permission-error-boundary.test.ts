import { SELF } from 'cloudflare:test'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PostHogPermissionError, wrapError } from '@/lib/errors'
import { StateManager } from '@/lib/StateManager'

// End-to-end worker → durable-object → boundary test for the bug reported
// against `https://mcp.posthog.com/mcp`: an OAuth-issued bearer token
// (DCR or CIMD, prefix `pha_`) on the JSON-RPC `initialize` request returns
// HTTP 500 / `Internal server error` instead of a structured 403
// `insufficient_scope` challenge when the token lacks a scope that MCP
// `init()` needs (e.g. `user:read` for `_fetchUser`).
//
// Personal API keys (`phx_`) work because they're issued with the full
// "MCP Server" scope preset; CIMD/DCR tokens carry only the scopes the
// client app declared in its registration, so they regularly miss
// `user:read` and trip the `_fetchUser → wrapError(..., PostHogPermissionError)`
// path inside the durable object.
//
// Hypothesis under test: `findPostHogPermissionError` (errors.ts:212) walks
// the `Error.cause` chain looking for an `instanceof PostHogPermissionError`,
// but the Cloudflare DO RPC boundary serializes thrown errors and drops both
// `cause` and the custom-subclass prototype. The detector returns undefined,
// `onCatchErrorHandler` falls through to the "unrecognized error → opaque
// 500" branch (index.ts), and the OAuth-aware client never receives the
// 403 + `WWW-Authenticate: Bearer error="insufficient_scope"` it needs to
// trigger re-consent.

const initializeBody = JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'initialize',
    params: {
        protocolVersion: '2025-03-26',
        capabilities: {},
        clientInfo: { name: 'Neptune', version: '1.0.0' },
    },
})

function buildWrappedPermissionError(): Error {
    // Same shape as `_fetchUser` (StateManager.ts:25): a generic Error wrapping
    // the typed PostHogPermissionError as its cause. Inside the DO this object
    // walks just fine; across the RPC boundary the cause and prototype are gone.
    const original = new PostHogPermissionError({
        detail: "API key missing required scope 'user:read'",
        missingScope: 'user:read',
        url: 'https://us.posthog.com/api/users/@me/',
        method: 'GET',
    })
    return wrapError(`Failed to get user: ${original.message}`, original)
}

describe('OAuth permission errors thrown inside the MCP durable object', () => {
    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('initialize with a CIMD/DCR token missing user:read returns 403 with insufficient_scope challenge', async () => {
        // Force the DO's init() path to fail the way a CIMD/DCR token without
        // `user:read` does in production: getApiKey resolves cleanly (OAuth
        // introspection says the token is active), then getUser throws the
        // wrapped PostHogPermissionError that `_fetchUser` constructs.
        vi.spyOn(StateManager.prototype, 'getApiKey').mockResolvedValue({
            scopes: [],
            scoped_teams: [],
            scoped_organizations: [],
        })
        vi.spyOn(StateManager.prototype, 'getUser').mockImplementation(async () => {
            throw buildWrappedPermissionError()
        })

        const response = await SELF.fetch('https://mcp.posthog.com/mcp', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                Accept: 'application/json, text/event-stream',
                Authorization: 'Bearer pha_test_oauth_token_for_dcr_client',
            },
            body: initializeBody,
        })
        // Drain the body so the response stream is closed before the test
        // teardown pops the DO storage frame.
        const body = await response.text()

        // The fix: insufficient-scope responses must be 403 (RFC 6750 §3.1)
        // so MCP-SDK clients can recover. 500 here is the bug — a generic
        // server error short-circuits the SDK's `auth()` recovery branch
        // and the user sees "Internal server error" forever.
        expect(response.status).toBe(403)

        const challenge = response.headers.get('www-authenticate')
        expect(challenge).toBeTruthy()
        expect(challenge).toContain('error="insufficient_scope"')
        expect(challenge).toContain('scope="user:read"')

        expect(body).toContain("'user:read'")
        expect(body).toContain('MCP Server')
    })
})
