import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import {
    buildInsufficientScopeChallenge,
    findPostHogPermissionError,
    formatPermissionErrorMessage,
    handleToolError,
    PostHogApiError,
    PostHogPermissionError,
    PostHogValidationError,
    wrapError,
} from '@/lib/errors'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException }),
}))
vi.mock('@/lib/posthog/analytics', () => ({
    AnalyticsEvent: { MCP_TOOL_CALL: '$mcp_tool_call' },
}))
vi.mock('@/lib/posthog/flags', () => ({
    isFeatureFlagEnabled: vi.fn().mockResolvedValue(false),
}))

const permissionDeniedBody = JSON.stringify({
    type: 'authentication_error',
    code: 'permission_denied',
    detail: "API key missing required scope 'user:read'",
    attr: null,
})

describe('PostHogPermissionError', () => {
    it('builds message with missing scope', () => {
        const error = new PostHogPermissionError({
            detail: "API key missing required scope 'user:read'",
            missingScope: 'user:read',
            url: 'https://us.posthog.com/api/users/@me/',
            method: 'GET',
        })

        expect(error.message).toBe("Missing PostHog API scope: 'user:read'")
        expect(error.missingScope).toBe('user:read')
        expect(error.name).toBe('PostHogPermissionError')
    })

    it('builds message without missing scope', () => {
        const error = new PostHogPermissionError({
            detail: 'you do not have access to this team',
            url: 'https://us.posthog.com/api/projects/47074/',
            method: 'GET',
        })

        expect(error.message).toContain('PostHog API permission denied')
        expect(error.missingScope).toBeUndefined()
    })
})

describe('formatPermissionErrorMessage', () => {
    it('names the missing scope and points to remediation', () => {
        const error = new PostHogPermissionError({
            detail: "API key missing required scope 'user:read'",
            missingScope: 'user:read',
            url: 'https://us.posthog.com/api/users/@me/',
            method: 'GET',
        })

        const text = formatPermissionErrorMessage(error)

        expect(text).toContain("'user:read'")
        expect(text).toContain('MCP Server')
        expect(text).toContain('GET https://us.posthog.com/api/users/@me/')
    })

    it('falls back to generic remediation when no scope is parsed', () => {
        const error = new PostHogPermissionError({
            detail: 'team access denied',
            url: 'https://us.posthog.com/api/projects/47074/',
            method: 'GET',
        })

        const text = formatPermissionErrorMessage(error)

        expect(text).toContain('PostHog API permission denied')
        expect(text).toContain('HTTP 403')
    })
})

describe('buildInsufficientScopeChallenge', () => {
    it('follows RFC 6750 §3.1 when a scope is known', () => {
        const error = new PostHogPermissionError({
            detail: "API key missing required scope 'user:read'",
            missingScope: 'user:read',
            url: 'https://us.posthog.com/api/users/@me/',
            method: 'GET',
        })

        expect(buildInsufficientScopeChallenge(error)).toBe(
            'Bearer error="insufficient_scope", scope="user:read", error_description="API key missing required scope \'user:read\'"'
        )
    })

    it('omits scope when unknown', () => {
        const error = new PostHogPermissionError({
            detail: 'team access denied',
            url: 'https://us.posthog.com/api/projects/1/',
            method: 'GET',
        })

        expect(buildInsufficientScopeChallenge(error)).toBe(
            'Bearer error="insufficient_scope", error_description="team access denied"'
        )
    })

    it('strips control chars and balances quotes in detail', () => {
        const error = new PostHogPermissionError({
            detail: 'hi "there"\nthis is bad',
            missingScope: 'user:read',
            url: 'https://us.posthog.com/api/users/@me/',
            method: 'GET',
        })

        const header = buildInsufficientScopeChallenge(error)
        // Double quotes inside error_description must be swapped out and newlines dropped.
        expect(header).not.toMatch(/"there"/)
        expect(header).not.toMatch(/\n/)
        expect(header).toContain(`error_description="hi 'there'this is bad"`)
    })
})

describe('findPostHogPermissionError', () => {
    it('returns the error directly when instance matches', () => {
        const original = new PostHogPermissionError({
            detail: 'x',
            missingScope: 'user:read',
            url: 'https://us.posthog.com/api/users/@me/',
            method: 'GET',
        })

        expect(findPostHogPermissionError(original)).toBe(original)
    })

    it('walks Error.cause chains', () => {
        const original = new PostHogPermissionError({
            detail: 'x',
            missingScope: 'user:read',
            url: 'https://us.posthog.com/api/users/@me/',
            method: 'GET',
        })
        const wrapped = wrapError(`Failed to get user: ${original.message}`, original)
        const doubleWrapped = wrapError('Tool failed', wrapped)

        expect(findPostHogPermissionError(doubleWrapped)).toBe(original)
    })

    it('returns undefined for unrelated errors', () => {
        expect(findPostHogPermissionError(new Error('boom'))).toBeUndefined()
        expect(findPostHogPermissionError('string error')).toBeUndefined()
        expect(findPostHogPermissionError(undefined)).toBeUndefined()
    })

    it('does not loop on self-referential cause', () => {
        const err: Error & { cause?: unknown } = new Error('loop')
        err.cause = err
        expect(findPostHogPermissionError(err)).toBeUndefined()
    })

    // Cloudflare Durable Object RPC strips Error.cause and the custom subclass
    // prototype on the way out of the DO. Only `name`, `message`, and `stack`
    // survive. Without a message-shape fallback, init-time permission failures
    // get mapped to opaque 500s and OAuth-aware MCP clients never see the
    // 403 + insufficient_scope challenge they need to re-consent.
    describe('boundary-stripped errors (DO RPC fallback)', () => {
        it('reconstructs a PostHogPermissionError from a plain Error whose message carries the missing-scope literal', () => {
            const stripped = new Error("Failed to get user: Missing PostHog API scope: 'user:read'")

            const recovered = findPostHogPermissionError(stripped)

            expect(recovered).toBeInstanceOf(PostHogPermissionError)
            expect(recovered?.missingScope).toBe('user:read')
        })

        it('handles double-quoted scope literal', () => {
            const stripped = new Error('Failed to do thing: Missing PostHog API scope: "insight:write"')

            const recovered = findPostHogPermissionError(stripped)

            expect(recovered?.missingScope).toBe('insight:write')
        })

        it('returns undefined for unrelated error messages even when shape-similar', () => {
            expect(findPostHogPermissionError(new Error('Something about scope but not the literal'))).toBeUndefined()
            expect(findPostHogPermissionError(new Error('Missing PostHog API scope without quotes'))).toBeUndefined()
        })
    })
})

describe('handleToolError with permission errors', () => {
    it('returns a structured CallToolResult with remediation text', () => {
        const error = new PostHogPermissionError({
            detail: "API key missing required scope 'user:read'",
            missingScope: 'user:read',
            url: 'https://us.posthog.com/api/users/@me/',
            method: 'GET',
        })

        const result = handleToolError(error, 'users-me')

        expect(result.isError).toBe(true)
        const [content] = result.content as Array<{ type: string; text: string }>
        expect(content?.type).toBe('text')
        expect(content?.text).toContain('[users-me]')
        expect(content?.text).toContain("'user:read'")
        expect(content?.text).toContain('MCP Server')
    })

    it('fingerprints per tool to avoid dogpiling multiple tools into one issue', () => {
        captureException.mockClear()
        const error = new PostHogPermissionError({
            detail: "API key missing required scope 'user:read'",
            missingScope: 'user:read',
            url: 'https://us.posthog.com/api/users/@me/',
            method: 'GET',
        })

        handleToolError(error, 'insights-list')
        handleToolError(error, 'dashboards-list')

        const fingerprints = captureException.mock.calls.map(([, , props]) => props.$exception_fingerprint)
        expect(fingerprints).toEqual([
            'posthog-permission-error:insights-list:user:read',
            'posthog-permission-error:dashboards-list:user:read',
        ])
    })

    it('unwraps permission errors hidden behind Error.cause', () => {
        const original = new PostHogPermissionError({
            detail: "API key missing required scope 'insight:read'",
            missingScope: 'insight:read',
            url: 'https://us.posthog.com/api/projects/1/insights/',
            method: 'GET',
        })
        const wrapped = wrapError(`Failed to list insights: ${original.message}`, original)

        const result = handleToolError(wrapped, 'insights-list')
        const [content] = result.content as Array<{ type: string; text: string }>

        expect(content?.text).toContain("'insight:read'")
    })
})

describe('ApiClient fetchJson on 403 permission_denied', () => {
    beforeEach(() => {
        vi.restoreAllMocks()
    })

    it('throws PostHogPermissionError with the parsed missingScope', async () => {
        const mockFetch = vi.fn().mockResolvedValue(
            new Response(permissionDeniedBody, {
                status: 403,
                statusText: 'Forbidden',
                headers: { 'Content-Type': 'application/json' },
            })
        )
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'phx_test',
            baseUrl: 'https://us.posthog.com',
        })

        const result = await client.users().me()

        expect(result.success).toBe(false)
        if (result.success) {
            throw new Error('expected failure')
        }
        expect(result.error).toBeInstanceOf(PostHogPermissionError)
        const permissionError = result.error as PostHogPermissionError
        expect(permissionError.missingScope).toBe('user:read')
        expect(permissionError.method).toBe('GET')
        expect(permissionError.url).toBe('https://us.posthog.com/api/users/@me/')

        vi.unstubAllGlobals()
    })

    it('still throws PostHogPermissionError when no scope is present in detail', async () => {
        const body = JSON.stringify({
            type: 'authentication_error',
            code: 'permission_denied',
            detail: 'You do not have access to this team.',
            attr: null,
        })
        const mockFetch = vi.fn().mockResolvedValue(
            new Response(body, {
                status: 403,
                statusText: 'Forbidden',
                headers: { 'Content-Type': 'application/json' },
            })
        )
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'phx_test',
            baseUrl: 'https://us.posthog.com',
        })

        const result = await client.users().me()

        expect(result.success).toBe(false)
        if (result.success) {
            throw new Error('expected failure')
        }
        expect(result.error).toBeInstanceOf(PostHogPermissionError)
        expect((result.error as PostHogPermissionError).missingScope).toBeUndefined()

        vi.unstubAllGlobals()
    })

    it('leaves non-permission 403s on the existing error path', async () => {
        const body = 'forbidden'
        const mockFetch = vi.fn().mockResolvedValue(
            new Response(body, {
                status: 403,
                statusText: 'Forbidden',
            })
        )
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'phx_test',
            baseUrl: 'https://us.posthog.com',
        })

        const result = await client.users().me()

        expect(result.success).toBe(false)
        if (result.success) {
            throw new Error('expected failure')
        }
        expect(result.error).not.toBeInstanceOf(PostHogPermissionError)
        expect(result.error.message).toContain('Request failed')

        vi.unstubAllGlobals()
    })

    it('preserves PostHogPermissionError when surfaced via ApiClient.request()', async () => {
        const mockFetch = vi.fn().mockResolvedValue(
            new Response(permissionDeniedBody, {
                status: 403,
                statusText: 'Forbidden',
                headers: { 'Content-Type': 'application/json' },
            })
        )
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'phx_test',
            baseUrl: 'https://us.posthog.com',
        })

        await expect(client.request({ method: 'GET', path: '/api/users/@me/' })).rejects.toBeInstanceOf(
            PostHogPermissionError
        )

        vi.unstubAllGlobals()
    })
})

// Regression: an LLM agent passing a placeholder UUID to an MCP tool produced
// a 404, and `handleToolError` captured it as a PostHog exception fingerprinted
// by tool name — creating a brand-new error tracking issue per tool every time
// an agent fumbled a parameter. `handleToolError` must treat 4xx (and
// validation errors) as recoverable agent input and reserve `captureException`
// for 5xx and unexpected non-HTTP errors.
describe('handleToolError with API errors', () => {
    beforeEach(() => {
        captureException.mockClear()
    })

    // Boundary coverage: include 499 and 500 in the tables so an off-by-one
    // in the `status < 500` guard (e.g. `<=` instead of `<`) gets caught.
    it.each([
        { status: 400, statusText: 'Bad Request' },
        { status: 404, statusText: 'Not Found' },
        { status: 422, statusText: 'Unprocessable Entity' },
        { status: 499, statusText: 'Client Closed Request' },
    ])(
        'short-circuits $status PostHogApiError without capturing an exception',
        ({ status, statusText }: { status: number; statusText: string }) => {
            const error = new PostHogApiError({
                status,
                statusText,
                body: '{"detail":"Not found."}',
                url: 'https://us.posthog.com/api/environments/2/symbol_sets/00000000-0000-0000-0000-000000000000/',
                method: 'GET',
            })

            const result = handleToolError(error, 'error-tracking-symbol-sets-retrieve')

            expect(captureException).not.toHaveBeenCalled()
            expect(result.isError).toBe(true)
            const [content] = result.content as Array<{ type: string; text: string }>
            expect(content?.text).toContain('[error-tracking-symbol-sets-retrieve]')
            expect(content?.text).toContain(`Status Code: ${status}`)
        }
    )

    it.each([
        { status: 500, statusText: 'Internal Server Error' },
        { status: 502, statusText: 'Bad Gateway' },
        { status: 503, statusText: 'Service Unavailable' },
    ])(
        'captures $status PostHogApiError as an exception (real service failure)',
        ({ status, statusText }: { status: number; statusText: string }) => {
            const error = new PostHogApiError({
                status,
                statusText,
                body: '{"detail":"oops"}',
                url: 'https://us.posthog.com/api/environments/2/symbol_sets/abc/',
                method: 'GET',
            })

            const result = handleToolError(error, 'error-tracking-symbol-sets-retrieve')

            expect(captureException).toHaveBeenCalledTimes(1)
            expect(result.isError).toBe(true)
        }
    )

    it('short-circuits PostHogValidationError without capturing an exception', () => {
        const error = new PostHogValidationError({
            detail: 'invalid uuid',
            attr: 'id',
            code: 'invalid',
            extra: undefined,
            url: 'https://us.posthog.com/api/environments/2/symbol_sets/not-a-uuid/',
            method: 'GET',
        })

        const result = handleToolError(error, 'error-tracking-symbol-sets-retrieve')

        expect(captureException).not.toHaveBeenCalled()
        expect(result.isError).toBe(true)
        const [content] = result.content as Array<{ type: string; text: string }>
        expect(content?.text).toContain('Validation error')
        expect(content?.text).toContain('field: id')
    })

    it('unwraps a 4xx PostHogApiError hidden behind Error.cause', () => {
        const original = new PostHogApiError({
            status: 404,
            statusText: 'Not Found',
            body: '{"detail":"Not found."}',
            url: 'https://us.posthog.com/api/environments/2/symbol_sets/00000000-0000-0000-0000-000000000000/',
            method: 'GET',
        })
        const wrapped = wrapError('Failed to retrieve symbol set', original)

        const result = handleToolError(wrapped, 'error-tracking-symbol-sets-retrieve')

        expect(captureException).not.toHaveBeenCalled()
        expect(result.isError).toBe(true)
    })

    it('still captures unexpected non-HTTP errors', () => {
        const error = new Error('boom — something unexpected went wrong')

        const result = handleToolError(error, 'some-tool')

        expect(captureException).toHaveBeenCalledTimes(1)
        expect(result.isError).toBe(true)
    })
})
