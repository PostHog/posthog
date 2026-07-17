import { createHash } from 'node:crypto'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AnalyticsEvent } from '@/lib/posthog/analytics'

const mocks = vi.hoisted(() => ({
    capture: vi.fn(),
    getAnalyticsContext: vi.fn(),
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
    },
}))

import { buildCliContext } from '@/cli/context'

describe('CLI context', () => {
    beforeEach(() => {
        mocks.capture.mockClear()
        mocks.getDistinctId.mockReset()
        mocks.getAnalyticsContext.mockReset()
        mocks.getDistinctId.mockRejectedValue(new Error('offline'))
        mocks.getAnalyticsContext.mockRejectedValue(new Error('offline'))
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
            })
        )
    })
})
