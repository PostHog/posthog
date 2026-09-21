import { afterEach, describe, expect, it, vi } from 'vitest'

import { getPostHogClient } from '@/lib/posthog/client'

vi.mock('@/lib/env', () => ({
    env: {
        POSTHOG_ANALYTICS_API_KEY: 'phc_test',
        POSTHOG_ANALYTICS_HOST: 'https://example.com',
    },
}))

describe('PostHog client', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it.each([
        ['capture', false],
        ['capture', true],
        ['captureToolCall', false],
        ['captureToolCall', true],
    ] as const)('filters impersonated tool calls through %s with isError=%s', async (method, isError) => {
        const events: { event: string; properties: Record<string, unknown> }[] = []
        vi.stubGlobal(
            'fetch',
            vi.fn(async (_url: string, options: RequestInit) => {
                events.push(...JSON.parse(options.body as string).batch)
                return new Response('{}', { status: 200 })
            })
        )
        const client = getPostHogClient()

        for (const isImpersonated of [true, false, true]) {
            const properties = { is_impersonated: isImpersonated, $mcp_is_error: isError }
            if (method === 'captureToolCall') {
                client.captureToolCall({
                    distinctId: 'user-123',
                    toolName: 'user-get',
                    durationMs: 12,
                    isError,
                    properties,
                })
            } else {
                client.capture({ distinctId: 'user-123', event: '$mcp_tool_call', properties })
            }
        }
        client.capture({
            distinctId: 'user-123',
            event: 'mcp feedback submitted',
            properties: { is_impersonated: true },
        })
        client.capture({ distinctId: 'user-123', event: '$mcp_tool_call' })
        await client.flush()

        expect(events.map(({ event }) => event)).toEqual(['$mcp_tool_call', 'mcp feedback submitted', '$mcp_tool_call'])
        expect(events[0]?.properties).toMatchObject({ is_impersonated: false, $mcp_is_error: isError })
        expect(events[1]?.properties).toMatchObject({ is_impersonated: true })
    })
})
