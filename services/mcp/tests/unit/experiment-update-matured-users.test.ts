/**
 * `only_count_matured_users` is the escape hatch from a long conversion window:
 * while it is on, nobody counts until their window closes, so a young experiment
 * with a 14-day window reports 0 exposures on every metric. The tool must carry a
 * change to it through to the API — a param the allowlist omits is stripped by zod
 * and the caller gets a success for a setting that never moved.
 */
import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/experiments'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const PROJECT_ID = '2'

function getTool(): ToolBase<ZodObjectAny> {
    return (GENERATED_TOOLS['experiment-update'] as () => ToolBase<ZodObjectAny>)()
}

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request: requestMock, getProjectBaseUrl: () => `https://us.posthog.com/project/${PROJECT_ID}` } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue(PROJECT_ID) } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('experiment-update only_count_matured_users', () => {
    it.each([
        ['false', false],
        ['true', true],
    ])('sends %s through to the PATCH body and reports the stored value', async (_label, value) => {
        const requestMock = vi.fn().mockResolvedValue({ id: 123, name: 'Checkout', only_count_matured_users: value })
        const tool = getTool()
        const params = (tool.schema as z.ZodTypeAny).parse({
            id: '123',
            project_id: PROJECT_ID,
            only_count_matured_users: value,
        })

        const result = await tool.handler(createMockContext(requestMock), params)

        expect(requestMock).toHaveBeenCalledWith({
            method: 'PATCH',
            path: '/api/projects/2/experiments/123/',
            body: { only_count_matured_users: value },
        })
        expect(result).toMatchObject({ only_count_matured_users: value })
    })
})
