import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/data_warehouse'
import type { Context } from '@/tools/types'

const VIEW_ID = '00000000-0000-4000-8000-000000000001'

describe('Generated data warehouse view tools', () => {
    it.each([
        { name: 'view-run-history', input: { id: VIEW_ID }, response: { run_history: [] } },
        {
            name: 'view-unmaterialize',
            input: { id: VIEW_ID, name: 'orders', query: { kind: 'HogQLQuery', query: 'SELECT 1' } },
            response: undefined,
        },
    ])('$name links to the requested view when the response has no id', async ({ name, input, response }) => {
        const context = {
            api: {
                request: vi.fn().mockResolvedValue(response),
                getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
            },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const tool = GENERATED_TOOLS[name]!()

        const result = await tool.handler(context, tool.schema.parse(input))

        expect(result).toEqual({
            ...response,
            _posthogUrl: `https://us.posthog.com/project/42/sql?open_view=${VIEW_ID}`,
        })
    })
})
