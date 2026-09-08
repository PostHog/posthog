import type { HogFlow } from './hogflows/types'
import { prepareWorkflowDuplicate } from './workflowDuplication'

describe('prepareWorkflowDuplicate', () => {
    it('removes server-owned identity and product ownership fields', () => {
        const workflow = {
            id: 'workflow-id',
            team_id: 1,
            name: 'Loop workflow',
            status: 'active',
            created_at: '2026-09-01T00:00:00Z',
            updated_at: '2026-09-01T00:00:00Z',
            origin_product: 'loops',
            actions: [],
        } as unknown as HogFlow

        expect(prepareWorkflowDuplicate(workflow)).toEqual({
            name: 'Loop workflow (copy)',
            status: 'draft',
            actions: [],
        })
    })
})
