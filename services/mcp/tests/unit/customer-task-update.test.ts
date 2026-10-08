import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/customer_analytics'
import type { Context } from '@/tools/types'

describe('customer task updates', () => {
    it.each([{ status: 'completed' }, { account_id: null, assigned_to_id: null, due_at: null, description: null }])(
        'preserves omitted fields and forwards explicit changes: %j',
        async (changes) => {
            const request = vi.fn().mockResolvedValue({ id: '00000000-0000-4000-8000-000000000001' })
            const context = {
                api: { request },
                stateManager: { getProjectId: async () => '42' },
            } as unknown as Context
            const tool = GENERATED_TOOLS['customer-tasks-partial-update']!()
            const params = tool.schema.parse({ id: '00000000-0000-4000-8000-000000000001', ...changes })

            await tool.handler(context, params)

            expect(request).toHaveBeenCalledWith({
                method: 'PATCH',
                path: '/api/projects/42/customer_tasks/00000000-0000-4000-8000-000000000001/',
                body: changes,
            })
        }
    )
})
