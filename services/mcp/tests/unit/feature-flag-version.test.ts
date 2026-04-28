import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockIsFeatureEnabled = vi.fn()

vi.mock('posthog-node', () => ({
    PostHog: vi.fn().mockImplementation(() => ({
        isFeatureEnabled: mockIsFeatureEnabled,
    })),
}))

// Must import after vi.mock
import { isFeatureFlagEnabled } from '@/lib/analytics'

describe('isFeatureFlagEnabled', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('should return true when the flag is enabled', async () => {
        mockIsFeatureEnabled.mockResolvedValue(true)

        const result = await isFeatureFlagEnabled('mcp-version-2', 'user-123')
        expect(result).toBe(true)
        expect(mockIsFeatureEnabled).toHaveBeenCalledWith('mcp-version-2', 'user-123')
    })

    it('should return false when the flag is disabled', async () => {
        mockIsFeatureEnabled.mockResolvedValue(false)

        const result = await isFeatureFlagEnabled('mcp-version-2', 'user-123')
        expect(result).toBe(false)
    })

    it('should return false when the flag returns undefined', async () => {
        mockIsFeatureEnabled.mockResolvedValue(undefined)

        const result = await isFeatureFlagEnabled('mcp-version-2', 'user-123')
        expect(result).toBe(false)
    })

    it('should return false when the client throws', async () => {
        mockIsFeatureEnabled.mockRejectedValue(new Error('network error'))

        const result = await isFeatureFlagEnabled('mcp-version-2', 'user-123')
        expect(result).toBe(false)
    })
})
