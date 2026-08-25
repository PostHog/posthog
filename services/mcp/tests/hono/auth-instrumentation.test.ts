import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockCapture, mockCaptureException } = vi.hoisted(() => ({
    mockCapture: vi.fn(),
    mockCaptureException: vi.fn(),
}))

vi.mock('@/lib/posthog', () => ({
    getPostHogClient: vi.fn(() => ({
        capture: mockCapture,
        captureException: mockCaptureException,
    })),
}))

import { handleCatchError } from '@/hono/request-utils'
import { classifyAuthFailure } from '@/lib/auth-errors'
import { classifyAuthMethod } from '@/lib/auth-method'
import { ErrorCode, PostHogPermissionError, wrapError } from '@/lib/errors'
import type { RequestProperties } from '@/lib/request-properties'

function makeProps(overrides: Partial<RequestProperties> = {}): RequestProperties {
    return {
        apiToken: 'pha_oauth-token',
        userHash: 'token-hash',
        mcpClientName: 'claude-ai',
        mcpClientVersion: '0.1.0',
        clientUserAgent: 'Claude-User',
        mcpVendorClient: 'ClaudeAI',
        transport: 'streamable-http',
        region: 'us',
        ...overrides,
    }
}

function permissionError(missingScope?: string): PostHogPermissionError {
    return new PostHogPermissionError({
        detail: 'permission denied',
        missingScope,
        url: '/api/users/@me/',
        method: 'GET',
    })
}

describe('MCP auth instrumentation', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it.each([
        ['pha_abc123', 'oauth'],
        ['phx_abc123', 'personal_api_key'],
        ['', 'none'],
        [undefined, 'none'],
        ['not-a-posthog-token', 'unknown'],
    ])('classifies %s as %s', (token, expected) => {
        expect(classifyAuthMethod(token as string | undefined)).toBe(expected)
    })

    it('classifies an ID-JAG JWT ahead of the unknown fallback', () => {
        const header = Buffer.from(JSON.stringify({ typ: 'at+jwt', alg: 'RS256' })).toString('base64url')
        expect(classifyAuthMethod(`${header}.payload.signature`)).toBe('id_jag')
    })

    it.each([
        [() => permissionError('insight:read'), 'insufficient_scope', 403],
        [() => new Error(`boom ${ErrorCode.INACTIVE_OAUTH_TOKEN}`), 'inactive_oauth_token', 401],
        [() => new Error(`boom ${ErrorCode.INVALID_API_KEY}`), 'invalid_api_key', 401],
        [() => new Error('something else entirely'), 'unknown', undefined],
    ])('labels the failure as %#: %s with status %s', (build, reason, status) => {
        const failure = classifyAuthFailure(build())
        expect(failure.reason).toBe(reason)
        expect(failure.status).toBe(status)
    })

    it('finds the reason and missing scope through a wrapping error', () => {
        const failure = classifyAuthFailure(wrapError('Failed to get user', permissionError('query:read')))

        expect(failure.reason).toBe('insufficient_scope')
        expect(failure.missingScope).toBe('query:read')
    })

    it('captures $mcp_auth_failed for a rejected credential, keyed on the token hash', () => {
        const response = handleCatchError(new Error(`boom ${ErrorCode.INVALID_API_KEY}`), makeProps())

        expect(response.status).toBe(401)
        expect(mockCapture).toHaveBeenCalledTimes(1)
        const call = mockCapture.mock.calls[0]![0]
        expect(call.event).toBe('$mcp_auth_failed')
        expect(call.distinctId).toBe('token-hash')
        expect(call.properties).toMatchObject({
            $mcp_auth_failure_reason: 'invalid_api_key',
            $mcp_auth_status: 401,
            $mcp_auth_method: 'oauth',
            $mcp_client_name: 'claude-ai',
            mcp_vendor_client: 'ClaudeAI',
        })
        expect(call.properties.$mcp_missing_scope).toBeUndefined()
    })

    it('records the missing scope on a permission denial', () => {
        handleCatchError(permissionError('insight:read'), makeProps())

        expect(mockCapture.mock.calls[0]![0].properties).toMatchObject({
            $mcp_auth_failure_reason: 'insufficient_scope',
            $mcp_missing_scope: 'insight:read',
            $mcp_auth_status: 403,
        })
    })

    it('leaves the tool-call failure vocabulary alone', () => {
        // `$mcp_is_error` and `$mcp_error_status` mean "a tool call failed against the
        // PostHog API"; setting them here would fold auth refusals into tool error rates.
        handleCatchError(permissionError('insight:read'), makeProps())

        const properties = mockCapture.mock.calls[0]![0].properties
        expect(properties.$mcp_is_error).toBeUndefined()
        expect(properties.$mcp_error_status).toBeUndefined()
    })

    it('never sends the bearer token itself', () => {
        handleCatchError(permissionError(), makeProps({ apiToken: 'pha_super-secret' }))

        expect(JSON.stringify(mockCapture.mock.calls[0]![0])).not.toContain('pha_super-secret')
    })

    it('leaves non-auth failures on the exception path', () => {
        const response = handleCatchError(new Error('unrelated explosion'), makeProps())

        expect(response.status).toBe(500)
        expect(mockCapture).not.toHaveBeenCalled()
        expect(mockCaptureException).toHaveBeenCalledTimes(1)
    })
})
