import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import * as api from 'products/signals/frontend/generated/api'
import type { ReportSpendApi } from 'products/signals/frontend/generated/api.schemas'

import { reportSpendLogic } from './reportSpendLogic'

describe('reportSpendLogic', () => {
    const receipt = (incomplete: boolean, amount = 125): ReportSpendApi => ({
        generation: { total_spend: amount, incomplete },
        implementation: { total_spend: null, incomplete: false },
        shared_scout_runs: { total_spend: null, incomplete: false },
    })

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('refreshes unfinished receipts without task polling and stops when finalized', async () => {
        const request = jest
            .spyOn(api, 'signalsReportSpend')
            .mockResolvedValueOnce(receipt(true))
            .mockResolvedValue(receipt(false, 375))
        const logic = reportSpendLogic({ teamId: 1, reportId: 'report-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadSpendSuccess'])
            expect(logic.values.spend?.generation.total_spend).toBe(125)

            await jest.advanceTimersByTimeAsync(5000)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.spend?.generation.total_spend).toBe(375)

            await jest.advanceTimersByTimeAsync(300000)
            expect(request).toHaveBeenCalledTimes(2)
        } finally {
            logic.unmount()
        }
    })

    it('backs off and caps retries for receipts that never finalize', async () => {
        const request = jest.spyOn(api, 'signalsReportSpend').mockResolvedValue(receipt(true))
        const logic = reportSpendLogic({ teamId: 1, reportId: 'report-1' })
        logic.mount()
        try {
            await expectLogic(logic).toDispatchActions(['loadSpendSuccess'])
            for (const [index, delay] of [5000, 10000, 20000, 30000, 30000, 30000].entries()) {
                await jest.advanceTimersByTimeAsync(delay - 1)
                expect(request).toHaveBeenCalledTimes(index + 1)
                await jest.advanceTimersByTimeAsync(1)
                await expectLogic(logic).toFinishAllListeners()
                expect(request).toHaveBeenCalledTimes(index + 2)
            }
            await jest.advanceTimersByTimeAsync(300000)
            expect(request).toHaveBeenCalledTimes(7)

            await expectLogic(logic, () => logic.actions.refreshSpend()).toDispatchActions(['loadSpendSuccess'])
            expect(request).toHaveBeenCalledTimes(8)
        } finally {
            logic.unmount()
        }
        await jest.advanceTimersByTimeAsync(300000)
        expect(request).toHaveBeenCalledTimes(8)
    })
})
