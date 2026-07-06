import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockIsFeatureEnabled = vi.fn()
const mockGetAllFlags = vi.fn()
// Mock the client `flags.ts` consumes, not posthog-node directly: `getPostHogClient()`
// returns a `PostHogMCP` (a posthog-node subclass) from the externalized
// `@posthog/mcp-analytics`, whose internal posthog-node import a `vi.mock('posthog-node')`
// here would not intercept.
vi.mock('@/lib/posthog/client', () => ({
    getPostHogClient: () => ({
        isFeatureEnabled: mockIsFeatureEnabled,
        getAllFlags: mockGetAllFlags,
    }),
}))

// Must import after vi.mock
import { evaluateFeatureFlags, isFeatureFlagEnabled } from '@/lib/posthog/flags'

describe('isFeatureFlagEnabled', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('should return true when the flag is enabled', async () => {
        mockIsFeatureEnabled.mockResolvedValue(true)

        const result = await isFeatureFlagEnabled('mcp-version-2', 'user-123')
        expect(result).toBe(true)
        expect(mockIsFeatureEnabled).toHaveBeenCalledWith('mcp-version-2', 'user-123', undefined)
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

    it('should forward groups as options when provided', async () => {
        mockIsFeatureEnabled.mockResolvedValue(true)

        await isFeatureFlagEnabled('notebooks-collaboration', 'user-123', { organization: 'org-abc' })

        expect(mockIsFeatureEnabled).toHaveBeenCalledWith('notebooks-collaboration', 'user-123', {
            groups: { organization: 'org-abc' },
        })
    })

    it('should omit the options arg when groups is an empty object', async () => {
        mockIsFeatureEnabled.mockResolvedValue(true)

        await isFeatureFlagEnabled('flag-x', 'user-123', {})

        expect(mockIsFeatureEnabled).toHaveBeenCalledWith('flag-x', 'user-123', undefined)
    })
})

describe('evaluateFeatureFlags', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('should evaluate multiple flags via getAllFlags and forward groups', async () => {
        mockGetAllFlags.mockResolvedValue({ 'flag-on': true, 'flag-off': false, unrelated: true })

        const result = await evaluateFeatureFlags(['flag-on', 'flag-off'], 'user-123', { organization: 'org-abc' })

        expect(result).toEqual({ 'flag-on': true, 'flag-off': false })
        expect(mockGetAllFlags).toHaveBeenCalledWith('user-123', {
            flagKeys: ['flag-on', 'flag-off'],
            groups: { organization: 'org-abc' },
        })
    })

    it('should omit groups when not provided', async () => {
        mockGetAllFlags.mockResolvedValue({ 'flag-a': true })

        await evaluateFeatureFlags(['flag-a'], 'user-123')

        expect(mockGetAllFlags).toHaveBeenCalledWith('user-123', { flagKeys: ['flag-a'] })
    })

    it('should short-circuit when no flag keys are requested', async () => {
        const result = await evaluateFeatureFlags([], 'user-123', { organization: 'org-abc' })

        expect(result).toEqual({})
        expect(mockGetAllFlags).not.toHaveBeenCalled()
    })
})
