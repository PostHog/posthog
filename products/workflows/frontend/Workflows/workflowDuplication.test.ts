import type { HogFlow } from './hogflows/types'
import { prepareWorkflowDuplicate } from './workflowDuplication'

describe('prepareWorkflowDuplicate', () => {
    it('removes server-owned identity, product ownership and code ownership fields', () => {
        const workflow = {
            id: 'workflow-id',
            key: 'loop-workflow',
            team_id: 1,
            name: 'Loop workflow',
            status: 'active',
            created_at: '2026-09-01T00:00:00Z',
            updated_at: '2026-09-01T00:00:00Z',
            origin_product: 'loops',
            managed_by: 'code',
            created_via: 'api',
            source_repository: 'github.com/example/flows',
            source_path: 'workflows/welcome.ts',
            source_ref: '9f2c1ab',
            actions: [],
        } as unknown as HogFlow

        expect(prepareWorkflowDuplicate(workflow)).toEqual({
            name: 'Loop workflow (copy)',
            status: 'draft',
            actions: [],
        })
    })
})
