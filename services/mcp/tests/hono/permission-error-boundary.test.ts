import { describe, expect, it } from 'vitest'

import { handleCatchError } from '@/hono/request-utils'
import { PostHogPermissionError, wrapError } from '@/lib/errors'
import type { RequestProperties } from '@/lib/request-properties'

// All `/mcp` traffic now flows through the Hono request path, so the OAuth
// permission-error boundary lives here (`handleCatchError`) rather than at the
// old CF worker → durable-object edge. When init or tool work throws a
// permission error — e.g. a CIMD/DCR token missing `user:read` — the boundary
// must answer with a 403 + RFC 6750 `insufficient_scope` challenge so
// OAuth-aware MCP clients can re-consent, not an opaque 500.

function buildWrappedPermissionError(): Error {
    // Same shape as the StateManager `_fetchUser` path: a generic Error wrapping
    // the typed PostHogPermissionError as its cause.
    const original = new PostHogPermissionError({
        detail: "API key missing required scope 'user:read'",
        missingScope: 'user:read',
        url: 'https://us.posthog.com/api/users/@me/',
        method: 'GET',
    })
    return wrapError(`Failed to get user: ${original.message}`, original)
}

const props = { userHash: 'abc123', transport: 'streamable-http' } as RequestProperties

describe('handleCatchError permission boundary', () => {
    it('maps a wrapped permission error to a 403 insufficient_scope challenge', async () => {
        const response = handleCatchError(buildWrappedPermissionError(), props)

        expect(response.status).toBe(403)

        const challenge = response.headers.get('www-authenticate')
        expect(challenge).toContain('error="insufficient_scope"')
        expect(challenge).toContain('scope="user:read"')

        const body = await response.text()
        expect(body).toContain("'user:read'")
        expect(body).toContain('MCP Server')
    })
})
