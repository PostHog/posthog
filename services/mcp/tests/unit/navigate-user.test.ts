import { describe, expect, it, vi } from 'vitest'

import { navigateUserHandler } from '@/tools/links/navigate-user'
import type { Context } from '@/tools/types'

function createMockContext(): Context {
    return {
        api: {
            getProjectBaseUrl: (projectId: string): string =>
                projectId === '@current' ? 'https://us.posthog.com' : `https://us.posthog.com/project/${projectId}`,
        },
        stateManager: {
            getProjectId: vi.fn(async () => '354703'),
        },
    } as unknown as Context
}

describe('navigate-user', () => {
    const ctx = createMockContext()

    it('passes through a same-instance _posthogUrl verbatim', async () => {
        const url = 'https://us.posthog.com/project/354703/workflows/wf-1/workflow'
        expect(await navigateUserHandler(ctx, { url, params: {} })).toEqual({ url })
    })

    it('resolves a catalog path template like generate-app-url', async () => {
        const result = await navigateUserHandler(ctx, {
            url: '/persons/{uuid}',
            params: { uuid: '12857b3c-2916-536b-af70-1e43c442a942' },
        })
        expect(result.url).toBe('https://us.posthog.com/project/354703/persons/12857b3c-2916-536b-af70-1e43c442a942')
    })

    it.each([
        ['a foreign-origin URL', 'https://evil.example.com/project/354703/workflows'],
        ['a malformed URL', 'not a url'],
        ['a non-catalog path template', '/definitely/not/a/template'],
    ])('rejects %s', async (_label, url) => {
        await expect(navigateUserHandler(ctx, { url, params: {} })).rejects.toThrow()
    })
})
