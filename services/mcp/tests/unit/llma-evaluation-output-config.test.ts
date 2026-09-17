import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/ai_observability'
import type { Context } from '@/tools/types'

describe('llma-evaluation-update output settings', () => {
    it.each([
        { output_config: { true_is_failure: true } },
        { output_config: { true_is_failure: false } },
        { output_config: { allows_na: true } },
        { output_config: { allows_na: false } },
        { output_config: {} },
        { name: 'Renamed evaluation' },
    ])('only sends the supplied settings for %j', async (body) => {
        const request = vi.fn().mockResolvedValue({})
        const context = {
            api: { request },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
        } as unknown as Context
        const tool = GENERATED_TOOLS['llma-evaluation-update']!()

        await tool.handler(context, tool.schema.parse({ id: 'evaluation-1', ...body }) as never)

        expect(request).toHaveBeenCalledExactlyOnceWith({
            method: 'PATCH',
            path: '/api/projects/17/evaluations/evaluation-1/',
            body,
        })
    })
})
