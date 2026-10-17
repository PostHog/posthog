import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import type { ReportChartApi } from 'products/signals/frontend/generated/api.schemas'

import { reportChartLogic } from './reportChartLogic'

jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))

const snapshot = { results: [[3]], columns: ['count'], types: ['Int64'] }
const chart: ReportChartApi = {
    chart_id: 'events',
    title: 'Events',
    query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'SELECT count() FROM events' } },
    cached_results: snapshot,
    cached_results_at: dayjs().subtract(1, 'hour').toISOString(),
}

describe('reportChartLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.mocked(performQuery).mockReset()
    })

    it.each([true, false])('shows the snapshot while refreshing and preserves it on failure (%s)', async (succeeds) => {
        let finish: () => void = () => {}
        jest.mocked(performQuery).mockImplementation(
            () =>
                new Promise((resolve, reject) => {
                    finish = () =>
                        succeeds ? resolve({ ...snapshot, results: [[7]] }) : reject(new Error('Query failed'))
                })
        )
        const logic = reportChartLogic({ chart })
        logic.mount()
        try {
            expect(logic.values.cachedResults).toEqual(snapshot)
            finish()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.cachedResults).toEqual({ ...snapshot, results: succeeds ? [[7]] : [[3]] })
        } finally {
            logic.unmount()
        }
    })

    it('does not query again for a fresh snapshot', () => {
        const logic = reportChartLogic({ chart: { ...chart, cached_results_at: dayjs().toISOString() } })
        logic.mount()
        try {
            expect(logic.values.cachedResults).toEqual(snapshot)
            expect(performQuery).not.toHaveBeenCalled()
        } finally {
            logic.unmount()
        }
    })
})
