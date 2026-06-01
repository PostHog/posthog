import { describe, expect, it } from 'vitest'

import { parseMcpMode, sanitizeHeaderValue } from '@/lib/utils'

function parseIdFromRequest(
    request: { headers: { get: (name: string) => string | null } },
    url: URL,
    headerName: string,
    paramName: string
): string | undefined {
    return request.headers.get(headerName) || url.searchParams.get(paramName) || undefined
}

describe('URL Routing', () => {
    const testCases = [
        { path: '/mcp', params: '', expected: { path: '/mcp', features: undefined } },
        {
            path: '/mcp',
            params: '?features=dashboards',
            expected: { path: '/mcp', features: ['dashboards'] },
        },
        {
            path: '/mcp',
            params: '?features=dashboards,insights',
            expected: { path: '/mcp', features: ['dashboards', 'insights'] },
        },
        { path: '/sse', params: '', expected: { path: '/sse', features: undefined } },
        {
            path: '/sse',
            params: '?features=flags,org',
            expected: { path: '/sse', features: ['flags', 'org'] },
        },
        {
            path: '/sse/message',
            params: '',
            expected: { path: '/sse/message', features: undefined },
        },
        {
            path: '/sse/message',
            params: '?features=flags',
            expected: { path: '/sse/message', features: ['flags'] },
        },
    ]

    describe('Query parameter parsing', () => {
        it.each(testCases)('should parse $path$params correctly', ({ path, params, expected }) => {
            const url = new URL(`https://example.com${path}${params}`)

            expect(url.pathname).toBe(expected.path)

            const featuresParam = url.searchParams.get('features')
            const features = featuresParam ? featuresParam.split(',').filter(Boolean) : undefined
            expect(features).toEqual(expected.features)
        })
    })

    describe('Features string parsing', () => {
        const featureTests = [
            { input: 'dashboards,insights,flags', expected: ['dashboards', 'insights', 'flags'] },
            { input: 'dashboards', expected: ['dashboards'] },
            { input: 'dashboards,,insights,', expected: ['dashboards', 'insights'] },
            { input: '', expected: [] },
        ]

        it.each(featureTests)("should parse '$input' as $expected", ({ input, expected }) => {
            const features = input.split(',').filter(Boolean)
            expect(features).toEqual(expected)
        })
    })

    describe('Organization and project ID parsing', () => {
        const idParsingTests = [
            {
                description: 'organization ID from header',
                headers: { 'x-posthog-organization-id': 'org-123' },
                params: '',
                expectedOrgId: 'org-123',
                expectedProjectId: undefined,
            },
            {
                description: 'project ID from header',
                headers: { 'x-posthog-project-id': '456' },
                params: '',
                expectedOrgId: undefined,
                expectedProjectId: '456',
            },
            {
                description: 'both IDs from headers',
                headers: { 'x-posthog-organization-id': 'org-123', 'x-posthog-project-id': '456' },
                params: '',
                expectedOrgId: 'org-123',
                expectedProjectId: '456',
            },
            {
                description: 'organization ID from query param fallback',
                headers: {},
                params: '?organization_id=org-789',
                expectedOrgId: 'org-789',
                expectedProjectId: undefined,
            },
            {
                description: 'project ID from query param fallback',
                headers: {},
                params: '?project_id=101',
                expectedOrgId: undefined,
                expectedProjectId: '101',
            },
            {
                description: 'both IDs from query param fallbacks',
                headers: {},
                params: '?organization_id=org-789&project_id=101',
                expectedOrgId: 'org-789',
                expectedProjectId: '101',
            },
            {
                description: 'header takes precedence over query param',
                headers: { 'x-posthog-organization-id': 'header-org', 'x-posthog-project-id': 'header-proj' },
                params: '?organization_id=param-org&project_id=param-proj',
                expectedOrgId: 'header-org',
                expectedProjectId: 'header-proj',
            },
            {
                description: 'undefined when neither header nor query param provided',
                headers: {},
                params: '',
                expectedOrgId: undefined,
                expectedProjectId: undefined,
            },
        ]

        it.each(idParsingTests)(
            'should parse $description',
            ({ headers, params, expectedOrgId, expectedProjectId }) => {
                const url = new URL(`https://example.com/mcp${params}`)
                const request = {
                    headers: {
                        get: (name: string) => (headers as Record<string, string>)[name] ?? null,
                    },
                }

                const organizationId = parseIdFromRequest(request, url, 'x-posthog-organization-id', 'organization_id')
                const projectId = parseIdFromRequest(request, url, 'x-posthog-project-id', 'project_id')

                expect(organizationId).toBe(expectedOrgId)
                expect(projectId).toBe(expectedProjectId)
            }
        )
    })

    describe('MCP mode parsing', () => {
        const modeTests = [
            {
                description: 'undefined when neither header nor query param provided',
                headers: {} as Record<string, string>,
                params: '',
                expected: undefined,
            },
            {
                description: 'tools from header',
                headers: { 'x-posthog-mcp-mode': 'tools' },
                params: '',
                expected: 'tools' as const,
            },
            {
                description: 'cli from header',
                headers: { 'x-posthog-mcp-mode': 'cli' },
                params: '',
                expected: 'cli' as const,
            },
            {
                description: 'tools from query param',
                headers: {},
                params: '?mode=tools',
                expected: 'tools' as const,
            },
            {
                description: 'cli from query param',
                headers: {},
                params: '?mode=cli',
                expected: 'cli' as const,
            },
            {
                description: 'case-insensitive (CLI)',
                headers: { 'x-posthog-mcp-mode': 'CLI' },
                params: '',
                expected: 'cli' as const,
            },
            {
                description: 'whitespace-tolerant (" tools ")',
                headers: { 'x-posthog-mcp-mode': ' tools ' },
                params: '',
                expected: 'tools' as const,
            },
            {
                description: 'unknown value ignored',
                headers: { 'x-posthog-mcp-mode': 'banana' },
                params: '',
                expected: undefined,
            },
            {
                description: 'legacy exec value ignored (only tools or cli accepted)',
                headers: { 'x-posthog-mcp-mode': 'exec' },
                params: '',
                expected: undefined,
            },
            {
                description: 'header takes precedence over query param',
                headers: { 'x-posthog-mcp-mode': 'cli' },
                params: '?mode=tools',
                expected: 'cli' as const,
            },
        ]

        it.each(modeTests)('parses $description', ({ headers, params, expected }) => {
            const url = new URL(`https://example.com/mcp${params}`)
            const headerValue = headers['x-posthog-mcp-mode'] ?? null
            const queryValue = url.searchParams.get('mode')

            // Mirrors the merge order in `src/index.ts` — header wins over query param.
            expect(parseMcpMode(headerValue || queryValue)).toBe(expected)
        })
    })

    describe('MCP consumer parsing', () => {
        const consumerTests = [
            {
                description: 'undefined when neither header nor query param provided',
                headers: {} as Record<string, string>,
                params: '',
                expected: undefined,
            },
            {
                description: 'plugin from header',
                headers: { 'x-posthog-mcp-consumer': 'plugin' },
                params: '',
                expected: 'plugin',
            },
            {
                description: 'posthog-code from header',
                headers: { 'x-posthog-mcp-consumer': 'posthog-code' },
                params: '',
                expected: 'posthog-code',
            },
            {
                description: 'plugin from query param fallback',
                headers: {},
                params: '?consumer=plugin',
                expected: 'plugin',
            },
            {
                description: 'arbitrary value from query param fallback',
                headers: {},
                params: '?consumer=slack',
                expected: 'slack',
            },
            {
                description: 'header takes precedence over query param',
                headers: { 'x-posthog-mcp-consumer': 'plugin' },
                params: '?consumer=other',
                expected: 'plugin',
            },
            {
                description: 'whitespace is trimmed from header value',
                headers: { 'x-posthog-mcp-consumer': '  plugin  ' },
                params: '',
                expected: 'plugin',
            },
            {
                description: 'whitespace is trimmed from query param value',
                headers: {},
                params: '?consumer=%20%20plugin%20%20',
                expected: 'plugin',
            },
            {
                description: 'control characters are stripped',
                headers: { 'x-posthog-mcp-consumer': 'plugin\x00\x1b' },
                params: '',
                expected: 'plugin',
            },
        ]

        it.each(consumerTests)('parses $description', ({ headers, params, expected }) => {
            const url = new URL(`https://example.com/mcp${params}`)
            const headerValue = headers['x-posthog-mcp-consumer'] ?? null
            const queryValue = url.searchParams.get('consumer')

            // Mirrors the merge order in `src/index.ts` — header wins over query param,
            // and both flow through `sanitizeHeaderValue` (which strips control chars,
            // trims whitespace, and collapses empty results to `undefined`).
            const consumer = sanitizeHeaderValue(headerValue || queryValue || undefined)
            expect(consumer).toBe(expected)
        })
    })
})
