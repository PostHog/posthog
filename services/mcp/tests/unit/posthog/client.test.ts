import { gunzipSync } from 'node:zlib'
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
                const body =
                    typeof options.body === 'string' ? options.body : gunzipSync(options.body as Uint8Array).toString()
                events.push(...JSON.parse(body).batch)
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

        expect(events.filter(({ event }) => event === '$mcp_tool_call')).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    properties: expect.objectContaining({ is_impersonated: false, $mcp_is_error: isError }),
                }),
                expect.objectContaining({
                    properties: expect.not.objectContaining({ is_impersonated: expect.anything() }),
                }),
            ])
        )
        expect(events.find(({ event }) => event === 'mcp feedback submitted')?.properties).toMatchObject({
            is_impersonated: true,
        })
        expect(events).toHaveLength(3)
    })
})
