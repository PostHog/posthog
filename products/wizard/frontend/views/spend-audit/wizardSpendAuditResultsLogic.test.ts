import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { dashboardsBulkDeleteCreate, dashboardsRetrieve } from 'products/dashboards/frontend/generated/api'
import { notebooksRetrieve } from 'products/notebooks/frontend/generated/api'
import { insightsPartialUpdate, insightsRetrieve } from 'products/product_analytics/frontend/generated/api'

import { type WizardRunNotebookArtifact, wizardSpendAuditResultsLogic } from './wizardSpendAuditResultsLogic'

jest.mock('products/dashboards/frontend/generated/api', () => ({
    dashboardsRetrieve: jest.fn(),
    dashboardsBulkDeleteCreate: jest.fn(),
}))
jest.mock('products/notebooks/frontend/generated/api', () => ({ notebooksRetrieve: jest.fn() }))
jest.mock('products/product_analytics/frontend/generated/api', () => ({
    insightsRetrieve: jest.fn(),
    insightsPartialUpdate: jest.fn(),
}))

const notebook: WizardRunNotebookArtifact = {
    id: 'artifact-1',
    team_id: 1,
    run_id: 'run-1',
    artifact_type: 'notebook',
    short_id: 'nb123',
    dashboard_ids: [7],
    insight_ids: [11],
    created_at: '2026-11-05T00:00:00Z',
}

describe('wizardSpendAuditResultsLogic', () => {
    let logic: ReturnType<typeof wizardSpendAuditResultsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(notebooksRetrieve).mockResolvedValue({ title: 'Spend audit' } as any)
        jest.mocked(dashboardsRetrieve).mockResolvedValue({ name: 'Unused events' } as any)
        jest.mocked(insightsRetrieve).mockRejectedValue(new Error('not found'))
        logic = wizardSpendAuditResultsLogic({ projectId: '1', runId: 'run-1', notebook })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('lists an object it cannot load as deleted, and marks one deleted only after the delete succeeds', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.createdObjects).toEqual([
            expect.objectContaining({ kind: 'dashboard', id: 7, name: 'Unused events', deleted: false }),
            expect.objectContaining({ kind: 'insight', id: 11, deleted: true }),
        ])

        jest.mocked(dashboardsBulkDeleteCreate).mockResolvedValueOnce({ deleted: [], skipped: [{ id: 7 }] } as any)
        logic.actions.deleteObject(logic.values.createdObjects![0])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.createdObjects![0].deleted).toBe(false)
        expect(logic.values.deletingKey).toBeNull()

        jest.mocked(dashboardsBulkDeleteCreate).mockResolvedValueOnce({ deleted: [7], skipped: [] } as any)
        logic.actions.deleteObject(logic.values.createdObjects![0])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.createdObjects![0].deleted).toBe(true)
        expect(insightsPartialUpdate).not.toHaveBeenCalled()
    })
})
