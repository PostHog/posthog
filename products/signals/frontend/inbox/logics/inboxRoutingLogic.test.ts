/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inboxRoutingLogic } from './inboxRoutingLogic'

const page = (results: unknown[]): { count: number; results: unknown[]; next: null; previous: null } => ({
    results,
    count: results.length,
    next: null,
    previous: null,
})
const batch = {
    id: 'batch-1',
    domain_id: 'domain-1',
    status: 'preview',
    total: 0,
    changed: 0,
    skipped_claims: 0,
    skipped_changes: 0,
    error: '',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

describe('inboxRoutingLogic', () => {
    it('keeps preview separate from confirmation and clears the previous operation on close', async () => {
        initKeaTests()
        const apply = jest.fn(() => ({ ...batch, status: 'complete' }))
        useMocks({
            get: {
                '/api/projects/:id/signals/domains/': page([]),
                '/api/projects/:id/signals/domains/teams/': [],
                '/api/projects/:id/signals/routing_preferences/': page([]),
                '/api/projects/:id/signals/routing_preferences/suggestions/': [],
                '/api/projects/:id/signals/routing_batches/': page([]),
                '/api/projects/:id/signals/routing_batches/batch-1/': { ...batch, status: 'complete' },
                '/api/projects/:id/signals/routing_batches/batch-1/reports/': page([]),
            },
            post: {
                '/api/projects/:id/signals/routing_preferences/preview/': batch,
                '/api/projects/:id/signals/routing_batches/batch-1/apply/': apply,
            },
        })
        const logic = inboxRoutingLogic({ projectId: '997' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.previewDomain({ domainId: 'domain-1' })).toFinishAllListeners()
        expect(apply).not.toHaveBeenCalled()
        expect(logic.values.batch?.status).toBe('preview')
        expect(logic.values.batchVisible).toBe(true)
        await expectLogic(logic, () => logic.actions.applyBatch({ batchId: 'batch-1' })).toFinishAllListeners()
        expect(apply).toHaveBeenCalledTimes(1)
        logic.actions.closeBatch()
        expect(logic.values.batch).toBeNull()
        expect(logic.values.batchReports).toBeNull()
        expect(logic.values.batchVisible).toBe(false)
        logic.unmount()
    })
})
