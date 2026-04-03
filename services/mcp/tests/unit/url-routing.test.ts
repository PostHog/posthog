import { describe, expect, it } from 'vitest'

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
})
