import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { USER_AGENT, getUserAgent } from '@/lib/constants'

describe('ApiClient', () => {
    it('should create ApiClient with required config', () => {
        const client = new ApiClient({
            apiToken: 'test-token',
            baseUrl: 'https://example.com',
        })

        expect(client).toBeInstanceOf(ApiClient)
    })

    it('should use custom baseUrl when provided', () => {
        const customUrl = 'https://custom.example.com'
        const client = new ApiClient({
            apiToken: 'test-token',
            baseUrl: customUrl,
        })

        const baseUrl = (client as any).baseUrl
        expect(baseUrl).toBe(customUrl)
    })

    it('should send correct headers on fetch', async () => {
        const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'test-token-123',
            baseUrl: 'https://example.com',
        })

        // Call the private fetch method
        await (client as any).fetch('https://example.com/api/test', {
            method: 'POST',
            body: JSON.stringify({ key: 'value' }),
        })

        expect(mockFetch).toHaveBeenCalledOnce()
        const [, options] = mockFetch.mock.calls[0]!
        expect(options.headers).toEqual({
            Authorization: 'Bearer test-token-123',
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT,
            'X-PostHog-Client': 'mcp',
        })

        vi.unstubAllGlobals()
    })

    it('should send x-posthog-mcp-user-agent header when clientUserAgent is provided', async () => {
        const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'test-token-123',
            baseUrl: 'https://example.com',
            clientUserAgent: 'posthog/wizard 1.0.0',
        })

        await (client as any).fetch('https://example.com/api/test', {
            method: 'POST',
            body: JSON.stringify({ key: 'value' }),
        })

        expect(mockFetch).toHaveBeenCalledOnce()
        const [, options] = mockFetch.mock.calls[0]!
        expect(options.headers).toEqual({
            Authorization: 'Bearer test-token-123',
            'Content-Type': 'application/json',
            'User-Agent': getUserAgent({ clientUserAgent: 'posthog/wizard 1.0.0' }),
            'X-PostHog-Client': 'mcp',
            'x-posthog-mcp-user-agent': 'posthog/wizard 1.0.0',
        })

        vi.unstubAllGlobals()
    })

    it('forwards mcpConsumer as x-posthog-mcp-consumer without altering User-Agent', async () => {
        const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'test-token-123',
            baseUrl: 'https://example.com',
            mcpConsumer: 'plugin',
            mcpClientName: 'claude-code',
        })

        await (client as any).fetch('https://example.com/api/test', {
            method: 'POST',
            body: JSON.stringify({ key: 'value' }),
        })

        expect(mockFetch).toHaveBeenCalledOnce()
        const [, options] = mockFetch.mock.calls[0]!
        expect(options.headers).toEqual({
            Authorization: 'Bearer test-token-123',
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT,
            'X-PostHog-Client': 'mcp',
            'x-posthog-mcp-client-name': 'claude-code',
            'x-posthog-mcp-consumer': 'plugin',
        })

        vi.unstubAllGlobals()
    })

    it('forwards mcpConsumer alone when mcpClientName is missing', async () => {
        const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'test-token-123',
            baseUrl: 'https://example.com',
            mcpConsumer: 'slack',
        })

        await (client as any).fetch('https://example.com/api/test', { method: 'GET' })

        const [, options] = mockFetch.mock.calls[0]!
        expect(options.headers['User-Agent']).toBe(USER_AGENT)
        expect(options.headers['x-posthog-mcp-consumer']).toBe('slack')

        vi.unstubAllGlobals()
    })

    describe('insights().get() — overrides forwarding', () => {
        const variablesOverride =
            '{"019d4838-1da4-0000-33c7-2561bf01f1c9":{"code_name":"eventname","variableId":"019d4838-1da4-0000-33c7-2561bf01f1c9","value":"signed_up"}}'
        const filtersOverride = '{"date_from":"-7d"}'

        function setupClient(): { client: ApiClient; mockFetch: ReturnType<typeof vi.fn> } {
            const mockFetch = vi.fn()
            vi.stubGlobal('fetch', mockFetch)
            const client = new ApiClient({ apiToken: 'test-token', baseUrl: 'https://example.com' })
            return { client, mockFetch }
        }

        it('hits the retrieve endpoint with no query string when called by numeric id and no overrides', async () => {
            const { client, mockFetch } = setupClient()
            mockFetch.mockResolvedValueOnce(
                new Response(JSON.stringify({ id: 42, short_id: 'abc12345' }), { status: 200 })
            )

            await client.insights({ projectId: '1' }).get({ insightId: '42' })

            expect(mockFetch).toHaveBeenCalledTimes(1)
            const [url] = mockFetch.mock.calls[0]!
            expect(url).toBe('https://example.com/api/projects/1/insights/42/')

            vi.unstubAllGlobals()
        })

        it('hits the retrieve endpoint with the override query string when called by numeric id with overrides', async () => {
            const { client, mockFetch } = setupClient()
            mockFetch.mockResolvedValueOnce(
                new Response(JSON.stringify({ id: 42, short_id: 'abc12345' }), { status: 200 })
            )

            await client.insights({ projectId: '1' }).get({
                insightId: '42',
                variables_override: variablesOverride,
                filters_override: filtersOverride,
            })

            expect(mockFetch).toHaveBeenCalledTimes(1)
            const [url] = mockFetch.mock.calls[0]!
            expect(url).toContain('https://example.com/api/projects/1/insights/42/?')
            expect(url).toContain(`variables_override=${encodeURIComponent(variablesOverride)}`)
            expect(url).toContain(`filters_override=${encodeURIComponent(filtersOverride)}`)

            vi.unstubAllGlobals()
        })

        it('resolves short_id via the list endpoint in one hop when no overrides are provided', async () => {
            const { client, mockFetch } = setupClient()
            mockFetch.mockResolvedValueOnce(
                new Response(JSON.stringify({ results: [{ id: 42, short_id: 'abc12345' }] }), { status: 200 })
            )

            const result = await client.insights({ projectId: '1' }).get({ insightId: 'abc12345' })

            expect(mockFetch).toHaveBeenCalledTimes(1)
            const [url] = mockFetch.mock.calls[0]!
            expect(url).toContain('/api/projects/1/insights/?short_id=abc12345')
            expect(result.success).toBe(true)

            vi.unstubAllGlobals()
        })

        it('resolves short_id and applies overrides in a single list call', async () => {
            const { client, mockFetch } = setupClient()
            mockFetch.mockResolvedValueOnce(
                new Response(JSON.stringify({ results: [{ id: 42, short_id: 'abc12345' }] }), { status: 200 })
            )

            await client.insights({ projectId: '1' }).get({
                insightId: 'abc12345',
                variables_override: variablesOverride,
            })

            // The list endpoint runs the same InsightSerializer.to_representation
            // and applies overrides from query_params, so a single hop suffices.
            expect(mockFetch).toHaveBeenCalledTimes(1)
            const [url] = mockFetch.mock.calls[0]!
            expect(url).toContain('/api/projects/1/insights/?')
            expect(url).toContain('short_id=abc12345')
            expect(url).toContain(`variables_override=${encodeURIComponent(variablesOverride)}`)
            expect(url).not.toContain('filters_override')

            vi.unstubAllGlobals()
        })
    })
})
