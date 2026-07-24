import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as messagingApi from 'products/messaging/frontend/generated/api'

import { suppressionListLogic } from './suppressionListLogic'

describe('suppressionListLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('page-state failure isolation', () => {
        // Guards against the "silent-swallow catch returns previous rows -> kea-loaders treats it as
        // success -> currentPage still increments" bug. On a failed loadNextPage the counter must
        // stay put; otherwise the UI shows the wrong page number over old data, then permanently
        // skips the page it thought it advanced to.
        it('does not advance currentPage when loadNextPage fails', async () => {
            jest.spyOn(messagingApi, 'messagingSuppressionsSuppressionsRetrieve').mockRejectedValue(new Error('boom'))
            const logic = suppressionListLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadNextPage()
            }).toDispatchActions(['loadNextPageFailure'])

            expect(logic.values.currentPage).toBe(1)
        })

        it('does not roll back currentPage when loadPreviousPage fails', async () => {
            jest.spyOn(messagingApi, 'messagingSuppressionsSuppressionsRetrieve').mockRejectedValue(new Error('boom'))
            const logic = suppressionListLogic()
            logic.mount()
            logic.actions.setCurrentPage(3)

            await expectLogic(logic, () => {
                logic.actions.loadPreviousPage()
            }).toDispatchActions(['loadPreviousPageFailure'])

            expect(logic.values.currentPage).toBe(3)
        })
    })
})
