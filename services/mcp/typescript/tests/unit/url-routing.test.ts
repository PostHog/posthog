import { describe, expect, it } from 'vitest'

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
})
