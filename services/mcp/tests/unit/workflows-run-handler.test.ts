import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/workflows'
import type { Context } from '@/tools/types'

interface RequestArgs {
    method: string
    path: string
    body?: Record<string, unknown>
}

function createMockContext(): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn().mockResolvedValue({ status: 'success' })
    const context = {
        api: {
            request,
            getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/1'),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('1'),
            getOrgID: vi.fn(),
            getRegion: vi.fn().mockResolvedValue('us'),
        },
        env: { POSTHOG_BASE_URL: 'https://us.posthog.com' },
        sessionManager: {},
        cache: {},
        getDistinctId: async () => 'test',
    } as unknown as Context

    return { context, request }
}

const runTool = GENERATED_TOOLS['workflows-test-run']!()

describe('workflows-test-run handler', () => {
    it('posts to the invocations endpoint with the workflow id in the path', async () => {
        const { context, request } = createMockContext()

        await runTool.handler(context, {
            id: 'wf-123',
            globals: { event: { event: '$pageview', distinct_id: 'd1' } },
            mock_async_functions: true,
        })

        const call = request.mock.calls[0]![0] as RequestArgs
        expect(call.method).toBe('POST')
        expect(call.path).toBe('/api/projects/1/hog_flows/wf-123/invocations/')
    })

    it('forwards globals, mock_async_functions, and current_action_id in the body', async () => {
        const { context, request } = createMockContext()

        await runTool.handler(context, {
            id: 'wf-123',
            globals: { event: { event: '$pageview', distinct_id: 'd1' } },
            mock_async_functions: false,
            current_action_id: 'action_42',
        })

        const call = request.mock.calls[0]![0] as RequestArgs
        expect(call.body).toEqual({
            globals: { event: { event: '$pageview', distinct_id: 'd1' } },
            mock_async_functions: false,
            current_action_id: 'action_42',
        })
    })

    it('omits unset optional fields from the body', async () => {
        const { context, request } = createMockContext()

        await runTool.handler(context, { id: 'wf-123' })

        const call = request.mock.calls[0]![0] as RequestArgs
        expect(call.body).toEqual({})
    })
})
