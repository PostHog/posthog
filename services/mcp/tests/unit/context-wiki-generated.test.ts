import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/context_layer'
import type { Context } from '@/tools/types'

function createMockContext(request: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request } as any,
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('42'),
            getOrgID: vi.fn().mockRejectedValue(new Error('organization route must not be used')),
        } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('context wiki generated tools', () => {
    it('uses the project-nested route for ordinary task tokens', async () => {
        const request = vi.fn().mockResolvedValue({
            path: 'projects/42/spaces/activation-research.md',
            exists: false,
        })

        await GENERATED_TOOLS['context-wiki-channel-resolve']!().handler(createMockContext(request), {
            channel_id: 'channel-id',
        })

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/context_layer/agent/channel-pages/channel-id/',
        })
    })
})
