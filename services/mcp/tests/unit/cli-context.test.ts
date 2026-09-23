import { createHash } from 'node:crypto'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AnalyticsEvent } from '@/lib/posthog/analytics'

const mocks = vi.hoisted(() => ({
    capture: vi.fn(),
    getAnalyticsContext: vi.fn(),
    getApiKey: vi.fn(),
    getDistinctId: vi.fn(),
}))

vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({
        capture: mocks.capture,
    }),
}))

vi.mock('@/lib/StateManager', () => ({
    StateManager: class {
        getDistinctId = mocks.getDistinctId
        getAnalyticsContext = mocks.getAnalyticsContext
        getApiKey = mocks.getApiKey
    },
}))

import { buildCliContext } from '@/cli/context'

describe('CLI context', () => {
    beforeEach(() => {
        mocks.capture.mockClear()
        mocks.getDistinctId.mockReset()
        mocks.getAnalyticsContext.mockReset()
        mocks.getApiKey.mockReset()
        mocks.getDistinctId.mockRejectedValue(new Error('offline'))
        mocks.getAnalyticsContext.mockRejectedValue(new Error('offline'))
        mocks.getApiKey.mockRejectedValue(new Error('offline'))
    })

    it.each(['phx_secret-token', undefined])(
        'captures tool calls when identity resolution fails with API key %s',
        async (apiKey) => {
            const context = await buildCliContext({ apiKey, host: 'https://us.posthog.com', version: 2 })

            await expect(context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL)).resolves.toBeUndefined()

            const expectedId = apiKey
                ? `posthog-cli:${createHash('sha256').update(apiKey).digest('hex').slice(0, 16)}`
                : 'posthog-cli:anonymous'
            expect(mocks.capture).toHaveBeenCalledWith(
                expect.objectContaining({
                    distinctId: expectedId,
                    event: AnalyticsEvent.MCP_TOOL_CALL,
                    properties: expect.objectContaining({ is_impersonated: false }),
                })
            )
            if (apiKey) {
                expect(JSON.stringify(mocks.capture.mock.calls)).not.toContain(apiKey)
            }
        }
    )

    it('uses an opaque analytics distinct ID for feedback when identity resolution fails', async () => {
        const apiKey = 'phx_secret-token'
        const context = await buildCliContext({ apiKey, host: 'https://us.posthog.com', version: 2 })

        await context.trackEvent(AnalyticsEvent.MCP_FEEDBACK_SUBMITTED)

        const expectedHash = createHash('sha256').update(apiKey).digest('hex').slice(0, 16)
        expect(mocks.capture).toHaveBeenCalledWith(
            expect.objectContaining({
                distinctId: `posthog-cli:${expectedHash}`,
                event: AnalyticsEvent.MCP_FEEDBACK_SUBMITTED,
            })
        )
        expect(JSON.stringify(mocks.capture.mock.calls)).not.toContain(apiKey)
    })

    it('uses an anonymous analytics distinct ID for feedback without an API key', async () => {
        const context = await buildCliContext({ host: 'https://us.posthog.com', version: 2 })

        await context.trackEvent(AnalyticsEvent.MCP_FEEDBACK_SUBMITTED)

        expect(mocks.capture).toHaveBeenCalledWith(
            expect.objectContaining({
                distinctId: 'posthog-cli:anonymous',
                event: AnalyticsEvent.MCP_FEEDBACK_SUBMITTED,
                properties: expect.objectContaining({ $mcp_scope_preset: 'user' }),
            })
        )
    })

    it.each(Object.values(AnalyticsEvent).flatMap((event) => [true, false].map((value) => [event, value] as const)))(
        'passes impersonation status to the SDK for %s with impersonation %s',
        async (event, impersonated) => {
            mocks.getDistinctId.mockResolvedValue('user-123')
            mocks.getApiKey.mockResolvedValue({ scopes: [], is_impersonated: impersonated })
            const context = await buildCliContext({ host: 'https://us.posthog.com', version: 2 })

            await context.trackEvent(event, { is_impersonated: !impersonated })

            expect(mocks.capture).toHaveBeenCalledWith(
                expect.objectContaining({
                    distinctId: 'user-123',
                    event,
                    properties: expect.objectContaining({ is_impersonated: impersonated }),
                })
            )
        }
    )
})
