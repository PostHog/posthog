/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
// The global setup makes the controller a pass-through. The bulk claim makes its own per call, so the real one is safe here.
jest.unmock('lib/utils/concurrencyController')

import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport, SignalReportStatus } from '../types'
import { BULK_CLAIM_CONCURRENCY, inboxBulkActionsLogic } from './inboxBulkActionsLogic'

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

    // Each claim is a transactional write, so a large selection must not reach the server as one burst.
    it('keeps the number of claim requests in flight under the limit', async () => {
        let inFlight = 0
        let mostInFlight = 0
        useMocks({
            post: {
                '/api/projects/:team_id/signals/reports/:id/claim/': async ({ params }) => {
                    inFlight++
                    mostInFlight = Math.max(mostInFlight, inFlight)
                    await new Promise((resolve) => setTimeout(resolve, 0))
                    inFlight--
                    return [200, { id: params.id, assignee: null }]
                },
            },
        })
        const reports = Array.from(
            { length: BULK_CLAIM_CONCURRENCY * 3 },
            (_, index) => ({ id: `r-${index}`, status: SignalReportStatus.READY, assignee: null }) as SignalReport
        )

        await expectLogic(logic, () => logic.actions.bulkClaim(reports)).toDispatchActions(['bulkClaimSuccess'])

        expect(mostInFlight).toBe(BULK_CLAIM_CONCURRENCY)
    })

    it('clears the anchor when the anchor row leaves the list', async () => {
        logic.actions.setVisibleReportIds(['a', 'b', 'c'])
        logic.actions.toggleReportSelection('a')

        logic.actions.setVisibleReportIds(['b', 'c'])
        await expectLogic(logic, () => logic.actions.selectRange('c')).toMatchValues({
            selectedReportIds: ['c'],
        })
    })
})
