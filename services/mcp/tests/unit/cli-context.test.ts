import { createHash } from 'node:crypto'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AnalyticsEvent } from '@/lib/posthog/analytics'

const mocks = vi.hoisted(() => ({
    capture: vi.fn(),
    getAnalyticsContext: vi.fn(),
    getApiKey: vi.fn(),
    getUser: vi.fn(),
}))

vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({
        capture: mocks.capture,
    }),
}))

vi.mock('@/lib/StateManager', () => ({
    StateManager: class {
        getUser = mocks.getUser
        getAnalyticsContext = mocks.getAnalyticsContext
        getApiKey = mocks.getApiKey
    },
}))

import { buildCliContext } from '@/cli/context'

describe('CLI context', () => {
    beforeEach(() => {
        mocks.capture.mockClear()
        mocks.getUser.mockReset()
        mocks.getAnalyticsContext.mockReset()
        mocks.getApiKey.mockReset()
        mocks.getUser.mockRejectedValue(new Error('offline'))
        mocks.getAnalyticsContext.mockRejectedValue(new Error('offline'))
        mocks.getApiKey.mockRejectedValue(new Error('offline'))
    })

    it('uses an opaque analytics distinct ID when identity resolution fails', async () => {
        const apiKey = 'phx_secret-token'
        const context = await buildCliContext({ apiKey, host: 'https://us.posthog.com', version: 2 })

        await context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL)

        const expectedHash = createHash('sha256').update(apiKey).digest('hex').slice(0, 16)
        expect(mocks.capture).toHaveBeenCalledWith(
            expect.objectContaining({
                distinctId: `posthog-cli:${expectedHash}`,
            })
        )
        expect(JSON.stringify(mocks.capture.mock.calls)).not.toContain(apiKey)
    })

    it('uses an anonymous analytics distinct ID without an API key', async () => {
        const context = await buildCliContext({ host: 'https://us.posthog.com', version: 2 })

        await context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL)

        expect(mocks.capture).toHaveBeenCalledWith(
            expect.objectContaining({
                distinctId: 'posthog-cli:anonymous',
                properties: expect.objectContaining({ $mcp_scope_preset: 'user' }),
            })
        )
    })

    it.each([true, false])('handles tool-call capture when impersonation is %s', async (impersonated) => {
        mocks.getUser.mockResolvedValue({ distinct_id: 'user-123', is_impersonated: impersonated })
        const context = await buildCliContext({ host: 'https://us.posthog.com', version: 2 })

        await context.trackEvent(AnalyticsEvent.MCP_TOOL_CALL)

        if (impersonated) {
            expect(mocks.capture).not.toHaveBeenCalled()
        } else {
            expect(mocks.capture).toHaveBeenCalledWith(
                expect.objectContaining({ distinctId: 'user-123', event: '$mcp_tool_call' })
            )
        }
    })
})
