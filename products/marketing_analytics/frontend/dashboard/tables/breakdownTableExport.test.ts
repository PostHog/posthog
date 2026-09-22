import { buildExportRows } from './breakdownTableExport'
import { SESSIONS_PER_VISITOR_COLUMN, VISITORS_COLUMN } from './webStatsColumns'
import { WebStatsRow } from './webStatsRows'

describe('buildExportRows', () => {
    const rows: WebStatsRow[] = [
        { breakdownValue: 'Email', visitors: [10, 0], sessions: [25, 5] },
        { breakdownValue: 'Direct', visitors: [0, null] },
        { breakdownValue: 'Organic' },
    ]

    it.each([false, true])('exports zeros, unavailable ratios, and previous periods (compare=%s)', (compare) => {
        expect(
            buildExportRows({
                columns: [VISITORS_COLUMN, SESSIONS_PER_VISITOR_COLUMN],
                rows,
                breakdownLabel: 'Channel',
                breakdownValue: (row) => row.breakdownValue,
                compare,
            })
        ).toEqual(
            compare
                ? [
                      [
                          'Channel',
                          'Visitors (current)',
                          'Visitors (previous)',
                          'Sessions per visitor (current)',
                          'Sessions per visitor (previous)',
                      ],
                      ['Email', '10', '0', '2.50', ''],
                      ['Direct', '0', '', '', ''],
                      ['Organic', '', '', '', ''],
                  ]
                : [
                      ['Channel', 'Visitors', 'Sessions per visitor'],
                      ['Email', '10', '2.50'],
                      ['Direct', '0', ''],
                      ['Organic', '', ''],
                  ]
        )
    })
})
