import { WebStatsTableQueryResponse } from '~/queries/schema/schema-general'

import { webStatsRows } from './webStatsRows'

describe('webStatsRows', () => {
    it('pairs metrics by column name while preserving zero and missing comparisons', () => {
        const response = {
            columns: [
                'context.columns.sessions',
                'context.columns.breakdown_value',
                'context.columns.visitors',
                'context.columns.ui_fill_fraction',
                'context.columns.cross_sell',
            ],
            results: [
                [[0, 10], null, 0, 0.5, 'ignored'],
                [[12, null], 'Email', [7, 0], 1, 'ignored'],
            ],
        } as WebStatsTableQueryResponse

        expect(webStatsRows(response)).toEqual([
            { breakdownValue: '', sessions: [0, 10], visitors: [0, null] },
            { breakdownValue: 'Email', sessions: [12, null], visitors: [7, 0] },
        ])
    })

    it('leaves unavailable metrics absent instead of reporting zero', () => {
        expect(
            webStatsRows({
                columns: ['breakdown_value', 'visitors', 'sessions'],
                results: [['Direct', [null, 4], null]],
            } as WebStatsTableQueryResponse)
        ).toEqual([{ breakdownValue: 'Direct' }])
        expect(webStatsRows(undefined)).toEqual([])
    })
})
