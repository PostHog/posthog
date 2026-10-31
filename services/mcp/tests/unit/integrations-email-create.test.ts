import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/integrations'
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

describe('integrations-email-create', () => {
    const config = { email: 'hello@example.com', name: 'Example', provider: 'ses' }

    it('always sends kind email, whatever the caller passes', async () => {
        const request = vi.fn().mockResolvedValue({ id: 1, kind: 'email' })

        // `kind` is not in the advertised schema, so a caller reaching for another
        // integration here must not be able to create one through this tool.
        await GENERATED_TOOLS['integrations-email-create']!().handler(createMockContext(request), {
            kind: 'slack',
            config,
        } as any)

        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({
                method: 'POST',
                path: '/api/projects/42/integrations/',
                body: { config, kind: 'email' },
            })
        )
    })
})
