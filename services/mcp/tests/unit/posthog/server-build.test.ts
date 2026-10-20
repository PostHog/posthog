import { readFileSync } from 'node:fs'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PostHogMCP } from '@posthog/mcp-analytics'

vi.mock('node:fs', () => ({ readFileSync: vi.fn() }))
vi.mock('@posthog/mcp-analytics', () => ({ PostHogMCP: vi.fn() }))
vi.mock('@/lib/env', () => ({
    env: {
        POSTHOG_ANALYTICS_API_KEY: 'phc_test',
        POSTHOG_ANALYTICS_HOST: 'https://example.com',
    },
}))

import { getMCPServerBuild, getPostHogClient } from '@/lib/posthog/client'

const mockReadFileSync = vi.mocked(readFileSync)
const mockPostHogMCP = vi.mocked(PostHogMCP)

describe('getMCPServerBuild', () => {
    beforeEach(() => {
        mockReadFileSync.mockReset()
    })

    it('returns the deployed commit SHA', () => {
        mockReadFileSync.mockReturnValue('b3b941584bae0123\n')

        expect(getMCPServerBuild()).toBe('b3b941584bae0123')
    })

    it.each(['', 'unknown'])('omits an unavailable build value: %j', (build) => {
        mockReadFileSync.mockReturnValue(build)

        expect(getMCPServerBuild()).toBeUndefined()
    })

    it('omits the build when the file does not exist', () => {
        mockReadFileSync.mockImplementation(() => {
            throw new Error('missing')
        })

        expect(getMCPServerBuild()).toBeUndefined()
    })
})

describe('getPostHogClient', () => {
    it('passes the deployed build to the MCP analytics SDK', () => {
        mockReadFileSync.mockReturnValue('b3b941584bae0123\n')

        getPostHogClient()

        expect(mockPostHogMCP).toHaveBeenCalledWith(
            'phc_test',
            expect.objectContaining({ serverBuild: 'b3b941584bae0123' })
        )
    })
})
