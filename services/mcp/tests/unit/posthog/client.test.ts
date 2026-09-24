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
        ['capture', '$mcp_tool_call', false],
        ['capture', '$mcp_tool_call', true],
        ['captureToolCall', '$mcp_tool_call', false],
        ['captureToolCall', '$mcp_tool_call', true],
        ['captureInitialize', '$mcp_initialize', false],
        ['captureToolsList', '$mcp_tools_list', false],
        ['captureException', '$exception', true],
        ['capture', '$identify', false],
        ['capture', 'mcp feedback submitted', false],
        ['capture', '$ai_generation', false],
        ['capture', '$ai_span', false],
    ] as const)('filters impersonated events through %s for %s with isError=%s', async (method, eventName, isError) => {
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

        for (const isImpersonated of [true, false, true, undefined]) {
            const properties = {
                ...(isImpersonated === undefined ? {} : { is_impersonated: isImpersonated }),
                $mcp_is_error: isError,
            }
            if (method === 'captureToolCall') {
                client.captureToolCall({
                    distinctId: 'user-123',
                    toolName: 'user-get',
                    durationMs: 12,
                    isError,
                    properties,
                })
            } else if (method === 'captureInitialize') {
                client.captureInitialize({ distinctId: 'user-123', durationMs: 12, properties })
            } else if (method === 'captureToolsList') {
                client.captureToolsList({ distinctId: 'user-123', toolNames: ['user-get'], properties })
            } else if (method === 'captureException') {
                client.captureException(new Error('Test error'), 'user-123', properties)
            } else {
                client.capture({ distinctId: 'user-123', event: eventName, properties })
            }
        }
        await client.flush()

        expect(events).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    event: eventName,
                    properties: expect.objectContaining({ is_impersonated: false, $mcp_is_error: isError }),
                }),
                expect.objectContaining({
                    event: eventName,
                    properties: expect.not.objectContaining({ is_impersonated: expect.anything() }),
                }),
            ])
        )
        expect(events).toHaveLength(2)
    })
})
