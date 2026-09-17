import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOL_MAP } from '@/tools/generated'
import { getToolDefinition } from '@/tools/toolDefinitions'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

// `status` is a staleness classification, so a disabled flag reports `ACTIVE`. An agent that
// reads serving state from it gets the opposite of the truth, and the list tool trims the
// response to an allowlist, so `active` has to survive that trim.
describe('feature flag serving state', () => {
    it('feature-flag-get-all keeps active alongside status', async () => {
        const request = vi.fn().mockResolvedValue({
            results: [
                {
                    id: 7,
                    key: 'new-checkout',
                    name: 'New checkout',
                    active: false,
                    archived: false,
                    status: 'ACTIVE',
                    tags: [],
                    filters: { groups: [] },
                },
            ],
        })

        const result: any = await GENERATED_TOOL_MAP['feature-flag-get-all']!().handler(createMockContext(request), {
            active: 'false',
        })

        expect(result.results[0]).toMatchObject({ key: 'new-checkout', active: false, status: 'ACTIVE' })
        expect(result.results[0]).not.toHaveProperty('filters')
    })

    it.each(['feature-flag-get-all', 'feature-flag-get-definition', 'feature-flags-status-retrieve'])(
        '%s tells the agent to read serving state from active',
        (name) => {
            expect(getToolDefinition(name).description).toContain('serving state')
        }
    )

    it('feature-flag-get-all explains that the active filter matches the active field', () => {
        const schema: any = GENERATED_TOOL_MAP['feature-flag-get-all']!().schema
        expect(schema.shape.active.description).toContain('not on `status`')
    })
})
