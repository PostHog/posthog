import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AnalyticsService } from '@/server/services/analytics'
import { SessionManager } from '@/lib/utils/SessionManager'
import { createMockCache } from '../fixtures'

const mockCapture = vi.fn()

vi.mock('posthog-node', () => ({
    PostHog: vi.fn().mockImplementation(() => ({
        capture: mockCapture,
    })),
}))

describe('AnalyticsService', () => {
    let analyticsService: AnalyticsService
    let mockSessionManager: SessionManager

    beforeEach(() => {
        vi.clearAllMocks()
        const cache = createMockCache()
        mockSessionManager = new SessionManager(cache)
        vi.spyOn(mockSessionManager, 'getSessionUuid').mockResolvedValue('session-uuid-123')
        analyticsService = new AnalyticsService(mockSessionManager)
    })

    describe('track', () => {
        it('captures event with distinctId', async () => {
            await analyticsService.track('mcp tool call', 'user-123')

            expect(mockCapture).toHaveBeenCalledWith({
                distinctId: 'user-123',
                event: 'mcp tool call',
                properties: {},
            })
        })

        it('includes session UUID when sessionId provided', async () => {
            await analyticsService.track('mcp tool call', 'user-123', 'session-id')

            expect(mockCapture).toHaveBeenCalledWith({
                distinctId: 'user-123',
                event: 'mcp tool call',
                properties: {
                    $session_id: 'session-uuid-123',
                },
            })
            expect(mockSessionManager.getSessionUuid).toHaveBeenCalledWith('session-id')
        })

        it('includes additional properties', async () => {
            await analyticsService.track('mcp tool call', 'user-123', undefined, {
                tool: 'dashboard-get',
                valid_input: true,
            })

            expect(mockCapture).toHaveBeenCalledWith({
                distinctId: 'user-123',
                event: 'mcp tool call',
                properties: {
                    tool: 'dashboard-get',
                    valid_input: true,
                },
            })
        })

        it('combines session and additional properties', async () => {
            await analyticsService.track('mcp tool response', 'user-123', 'session-id', {
                tool: 'feature-flag-get',
            })

            expect(mockCapture).toHaveBeenCalledWith({
                distinctId: 'user-123',
                event: 'mcp tool response',
                properties: {
                    $session_id: 'session-uuid-123',
                    tool: 'feature-flag-get',
                },
            })
        })

        it('silently handles errors', async () => {
            mockCapture.mockImplementationOnce(() => {
                throw new Error('Network error')
            })

            await expect(
                analyticsService.track('mcp tool call', 'user-123')
            ).resolves.toBeUndefined()
        })
    })
})
