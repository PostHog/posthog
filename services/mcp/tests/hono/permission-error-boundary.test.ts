import { describe, expect, it, vi } from 'vitest'

import { handleCatchError } from '@/hono/request-utils'
import { PostHogPermissionError, wrapError } from '@/lib/errors'
import { InsufficientScopeError } from '@/lib/missing-scope'
import type { RequestProperties } from '@/lib/request-properties'

// All `/mcp` traffic now flows through the Hono request path, so the OAuth
// permission-error boundary lives here (`handleCatchError`) rather than at the
// old CF worker → durable-object edge. When init or tool work throws a
// permission error — e.g. a CIMD/DCR token missing `user:read` — the boundary
// must answer with a 403, not an opaque 500. The 403 carries the RFC 6750
// `insufficient_scope` challenge only when the API challenged a step-up token.

function buildWrappedPermissionError(challengeScopes?: string[]): Error {
    // Same shape as the StateManager `_fetchUser` path: a generic Error wrapping
    // the typed PostHogPermissionError as its cause.
    const original = new PostHogPermissionError({
        detail: "API key missing required scope 'user:read'",
        missingScope: 'user:read',
        challengeScopes,
        url: 'https://us.posthog.com/api/users/@me/',
        method: 'GET',
    })
    return wrapError(`Failed to get user: ${original.message}`, original)
}

const props = { userHash: 'abc123', transport: 'streamable-http' } as RequestProperties

describe('handleCatchError permission boundary', () => {
    it.each([
        {
            label: 'the API challenged a step-up token',
            challengeScopes: ['user:read', 'organization:read'],
            expectedChallenge: 'Bearer error="insufficient_scope", scope="user:read organization:read"',
        },
        {
            label: 'the API challenged a step-up token without naming scopes',
            challengeScopes: [],
            expectedChallenge: 'Bearer error="insufficient_scope", scope="user:read"',
        },
        { label: 'the token does not support step-up', challengeScopes: undefined, expectedChallenge: null },
    ])('maps a wrapped permission error to a 403 when $label', async ({ challengeScopes, expectedChallenge }) => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

        const response = handleCatchError(buildWrappedPermissionError(challengeScopes), props)

        expect(consoleError).toHaveBeenCalledTimes(expectedChallenge ? 0 : 1)
        consoleError.mockRestore()

        expect(response.status).toBe(403)
        expect(response.headers.get('www-authenticate')).toBe(expectedChallenge)

        const body = await response.text()
        expect(body).toContain("'user:read'")
        expect(body).toContain('MCP Server')
    })

    it('maps a step-up challenge thrown by a tool call to a 403 carrying it, without logging it as an error', () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

        const response = handleCatchError(new InsufficientScopeError(['insight:read', 'query:read']), props)

        expect(consoleError).not.toHaveBeenCalled()
        consoleError.mockRestore()

        expect(response.status).toBe(403)
        expect(response.headers.get('www-authenticate')).toBe(
            'Bearer error="insufficient_scope", scope="insight:read query:read"'
        )
    })
})
