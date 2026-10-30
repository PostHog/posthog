/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { signalsReportsBulkClaimBodyIdsMax } from 'products/signals/frontend/generated/api.zod'

import { inboxBulkActionsLogic } from './inboxBulkActionsLogic'

describe('inboxBulkActionsLogic', () => {
    let logic: ReturnType<typeof inboxBulkActionsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = inboxBulkActionsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // A write that timed out can still have saved, so a bulk action where every write failed must not leave the
    // lists showing the old state.
    it.each([
        {
            action: 'dismiss',
            run: () => logic.actions.bulkDismiss({ reason: 'wontfix_irrelevant', note: '', correctedRepository: null }),
        },
        { action: 'resolve', run: () => logic.actions.bulkResolve('no_action_needed', '') },
    ])('asks every surface to reload after a $action where every write failed', async ({ run }) => {
        useMocks({ post: { '/api/projects/:team_id/signals/reports/:id/state/': () => [500, {}] } })
        logic.actions.setSelectedReportIds(['r1', 'r2'])

        await expectLogic(logic, run).toDispatchActions([logic.actionCreators.reportWriteFailed(['r1', 'r2'])])
    })

    it('toggles a report in and out of the selection', async () => {
        await expectLogic(logic, () => {
            logic.actions.toggleReportSelection('a')
            logic.actions.toggleReportSelection('b')
        }).toMatchValues({ selectedReportIds: ['a', 'b'], selectedCount: 2, hasSelection: true })

        await expectLogic(logic, () => logic.actions.toggleReportSelection('a')).toMatchValues({
            selectedReportIds: ['b'],
            hasSelection: true,
        })
    })

    it('drops selected ids that are no longer in the list', async () => {
        logic.actions.setVisibleReportIds(['a', 'b', 'c'])
        logic.actions.toggleReportSelection('a')
        logic.actions.toggleReportSelection('c')

        await expectLogic(logic, () => logic.actions.setVisibleReportIds(['a', 'b'])).toMatchValues({
            selectedReportIds: ['a'],
        })
    })

    it('keeps the selection when the list only grows, as an extra page appends', async () => {
        logic.actions.setVisibleReportIds(['a', 'b'])
        logic.actions.toggleReportSelection('b')

        await expectLogic(logic, () => logic.actions.setVisibleReportIds(['a', 'b', 'c', 'd'])).toMatchValues({
            selectedReportIds: ['b'],
        })
    })

    it('selects the range between the anchor and the shift-clicked row, in either direction', async () => {
        logic.actions.setVisibleReportIds(['a', 'b', 'c', 'd'])
        logic.actions.toggleReportSelection('c')

        await expectLogic(logic, () => logic.actions.selectRange('a')).toMatchValues({
            selectedReportIds: ['c', 'a', 'b'],
            selectedCount: 3,
        })

        logic.actions.clearSelection()
        logic.actions.toggleReportSelection('b')
        await expectLogic(logic, () => logic.actions.selectRange('d')).toMatchValues({
            selectedReportIds: ['b', 'c', 'd'],
        })
    })

    it('treats a shift-click with no anchor as a plain toggle', async () => {
        logic.actions.setVisibleReportIds(['a', 'b', 'c'])

        await expectLogic(logic, () => logic.actions.selectRange('b')).toMatchValues({
            selectedReportIds: ['b'],
            selectionAnchorId: 'b',
        })
    })

    it('treats a shift-click as a plain toggle once a deselect emptied the selection', async () => {
        logic.actions.setVisibleReportIds(['a', 'b', 'c', 'd'])
        logic.actions.toggleReportSelection('a')
        logic.actions.toggleReportSelection('a')

        await expectLogic(logic, () => logic.actions.selectRange('d')).toMatchValues({
            selectedReportIds: ['d'],
        })
    })

    it('ranges only over the rows that are loaded', async () => {
        logic.actions.setVisibleReportIds(['a', 'b'])
        logic.actions.toggleReportSelection('a')

        // 'z' is on a page that has not been fetched, so there is no range to extend to.
        await expectLogic(logic, () => logic.actions.selectRange('z')).toMatchValues({ selectedReportIds: ['a'] })
    })

    it('clears the anchor when the anchor row leaves the list', async () => {
        logic.actions.setVisibleReportIds(['a', 'b', 'c'])
        logic.actions.toggleReportSelection('a')

        logic.actions.setVisibleReportIds(['b', 'c'])
        await expectLogic(logic, () => logic.actions.selectRange('c')).toMatchValues({
            selectedReportIds: ['c'],
        })
    })

    // The endpoint rejects a request over its id limit, so a larger selection must be split, or nothing is claimed.
    it('claims a selection over the endpoint limit in batches and counts every claim', async () => {
        const batchSizes: number[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/signals/reports/bulk_claim/': async ({ request }) => {
                    const { ids } = (await request.json()) as { ids: string[] }
                    batchSizes.push(ids.length)
                    return [200, { results: [], claimed_count: ids.length, conflict_count: 0, not_found_count: 0 }]
                },
            },
        })
        const reportIds = Array.from({ length: signalsReportsBulkClaimBodyIdsMax + 1 }, (_, index) => `r-${index}`)

        await expectLogic(logic, () => logic.actions.bulkClaim(reportIds)).toDispatchActions(['bulkClaimSuccess'])

        expect(batchSizes).toEqual([signalsReportsBulkClaimBodyIdsMax, 1])
    })
})
