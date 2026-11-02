import { describe, expect, it } from 'vitest'

import { createApiToolLibrary, toApiToolError } from '@/cli/library'
import {
    ExecCommandError,
    MCPToolResultError,
    PostHogApiError,
    PostHogPermissionError,
    PostHogRateLimitError,
    wrapError,
} from '@/lib/errors'
import { getToolDefinition } from '@/tools/toolDefinitions'

describe('CLI tool library', () => {
    const library = createApiToolLibrary()

    it('describes every tool with its catalog group and required scopes', () => {
        const tools = library.tools()

        expect(tools.length).toBeGreaterThan(0)
        for (const tool of tools) {
            const definition = getToolDefinition(tool.name)
            expect(tool.group).toBe(definition.category)
            expect(tool.requiredScopes).toEqual(definition.required_scopes ?? [])
            expect(tool.requiresAiConsent).toBe(definition.requires_ai_consent === true)
        }
        expect(tools.some((tool) => tool.requiresAiConsent)).toBe(true)
    })

    it.each([
        ['accepts valid input', { limit: 5 }, true],
        ['rejects input of the wrong type, naming the field', { limit: 'five' }, false],
    ])('validation %s', (_name, input, valid) => {
        const result = library.validate('feature-flag-get-all', input)

        expect(result.valid).toBe(valid)
        if (!result.valid) {
            expect(result.error).toContain('limit')
        }
    })

    it('lists the scopes a key is missing for a tool', () => {
        expect(library.missingScopes(['feature_flag:read'], ['feature_flag:read', 'insight:write'])).toEqual([
            'insight:write',
        ])
    })

    const request = { url: 'https://us.posthog.com/api/x', method: 'GET' }
    it.each([
        [
            'a refusal keeps the scope PostHog named',
            new PostHogPermissionError({ detail: 'denied', missingScope: 'insight:write', ...request }),
            { code: 'permission_denied', status: 403, missingScope: 'insight:write' },
        ],
        [
            'a rate limit is not a plain API error',
            new PostHogRateLimitError({ body: '', retryAfterSeconds: 5, ...request }),
            { code: 'rate_limited', status: 429 },
        ],
        [
            'an API error reads the DRF detail',
            new PostHogApiError({ status: 404, statusText: 'Not Found', body: '{"detail":"Not found."}', ...request }),
            { code: 'api_error', status: 404, message: 'Not found.' },
        ],
        [
            'a wrapped refusal keeps its scope',
            wrapError(
                'Failed to get organizations',
                new PostHogPermissionError({ detail: 'denied', missingScope: 'organization:read', ...request })
            ),
            { code: 'permission_denied', missingScope: 'organization:read' },
        ],
        [
            'a failed backend tool keeps its error type',
            new MCPToolResultError('Too many queries', 'rate_limited'),
            { code: 'rate_limited' },
        ],
        [
            'a missing confirmation keeps its own code',
            new ExecCommandError('needs --confirm', 'needs_confirmation'),
            { code: 'needs_confirmation' },
        ],
    ])('maps %s', (_name, error, expected) => {
        expect(toApiToolError(error)).toMatchObject(expected)
    })
})
