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

    it('folds mcpConsumer and mcpClientName into the User-Agent as <consumer>/<client>', async () => {
        const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'test-token-123',
            baseUrl: 'https://example.com',
            mcpConsumer: 'posthog-code',
            mcpClientName: 'claude-code',
        })

        await (client as any).fetch('https://example.com/api/test', {
            method: 'POST',
            body: JSON.stringify({ key: 'value' }),
        })

        expect(mockFetch).toHaveBeenCalledOnce()
        const [, options] = mockFetch.mock.calls[0]!
        // No x-posthog-mcp-consumer header is sent — the consumer signal is folded into the UA.
        expect(options.headers).toEqual({
            Authorization: 'Bearer test-token-123',
            'Content-Type': 'application/json',
            'User-Agent': `posthog-code/claude-code ${USER_AGENT}`,
            'X-PostHog-Client': 'mcp',
            'x-posthog-mcp-client-name': 'claude-code',
        })

        vi.unstubAllGlobals()
    })

    it('falls back to <consumer>/unknown when mcpClientName is missing', async () => {
        const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
        vi.stubGlobal('fetch', mockFetch)

        const client = new ApiClient({
            apiToken: 'test-token-123',
            baseUrl: 'https://example.com',
            mcpConsumer: 'slack',
        })

        await (client as any).fetch('https://example.com/api/test', { method: 'GET' })

        const [, options] = mockFetch.mock.calls[0]!
        expect(options.headers['User-Agent']).toBe(`slack/unknown ${USER_AGENT}`)

        vi.unstubAllGlobals()
    })
})
