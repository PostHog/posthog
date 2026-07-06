import { LemonBanner, LemonTable } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

/**
 * PROTOTYPE — visual exploration of the "group by" lens; the rows are mocked.
 * Behind the `logs-group-by` flag; nothing here queries the backend for results (the attribute
 * picker in the display bar searches real keys). The goal is to judge the UX shape before
 * building a real query runner.
 *
 * Column choice is deliberate — each column maps to a triage job:
 *  - value:     which entity is this (identity, the pivot for drill-in)
 *  - logs:      which groups are noisiest (default sort)
 *  - errors:    which groups are failing (the "show me what's broken" sort)
 *  - last seen: is it still happening
 * Anything that doesn't serve triage or drill-in (timeline art, duration, first seen) is out.
 */

interface MockGroupRow {
    value: string
    count: number
    errorCount: number
    lastSeenMinutesAgo: number
}

const MOCK_VALUES: Record<string, string[]> = {
    transaction_id: ['txn_9f3ab21c', 'txn_04e77d90', 'txn_b81c33fa', 'txn_5a2e01dd', 'txn_c9f04e12', 'txn_77ab90e3'],
    person_id: ['person_018f3a', 'person_02d417', 'person_0a99c1', 'person_11e402', 'person_1c07b9', 'person_23f8d0'],
    session_id: ['sess_a1b2c3', 'sess_d4e5f6', 'sess_071829', 'sess_3a4b5c', 'sess_9d8e7f', 'sess_616263'],
    'service.name': ['api', 'worker', 'ingestion', 'capture', 'feature-flags', 'billing'],
}

// Deterministic pseudo-variety so each attribute renders distinct-looking (but stable) rows.
function mockRowsFor(groupBy: string): MockGroupRow[] {
    const values = MOCK_VALUES[groupBy] ?? [`${groupBy}_a`, `${groupBy}_b`, `${groupBy}_c`, `${groupBy}_d`]
    return values.map((value, i) => ({
        value,
        count: [4183, 1962, 870, 412, 96, 23][i] ?? 10,
        errorCount: [37, 0, 214, 0, 3, 0][i] ?? 0,
        lastSeenMinutesAgo: [2, 45, 1, 118, 7, 31][i] ?? 60,
    }))
}

export function LogsGroupByResults({ groupBy }: { groupBy: string }): JSX.Element {
    const rows = mockRowsFor(groupBy)
    const totalLogs = rows.reduce((sum, r) => sum + r.count, 0)

    return (
        <div className="flex-1 min-h-0 overflow-auto" data-attr="logs-group-by-results">
            <LemonBanner type="warning" className="m-2">
                Prototype — grouped results are mocked. This visualizes the group-by lens; no real query runs.
            </LemonBanner>
            <div className="px-2 pb-1 text-muted text-xs">
                {humanFriendlyNumber(rows.length)} groups found (based on {humanFriendlyNumber(totalLogs)} logs)
            </div>
            <LemonTable
                columns={[
                    {
                        title: groupBy,
                        key: 'value',
                        render: (_, row) => <span className="font-mono text-xs">{row.value}</span>,
                    },
                    {
                        title: 'Logs',
                        key: 'count',
                        align: 'right',
                        render: (_, row) => humanFriendlyNumber(row.count),
                        sorter: (a, b) => a.count - b.count,
                    },
                    {
                        title: 'Errors',
                        key: 'errorCount',
                        align: 'right',
                        render: (_, row) =>
                            row.errorCount > 0 ? (
                                <span className="text-danger font-semibold">{humanFriendlyNumber(row.errorCount)}</span>
                            ) : (
                                <span className="text-muted">0</span>
                            ),
                        sorter: (a, b) => a.errorCount - b.errorCount,
                    },
                    {
                        title: 'Last seen',
                        key: 'lastSeen',
                        render: (_, row) => <TZLabel time={dayjs().subtract(row.lastSeenMinutesAgo, 'minute')} />,
                        sorter: (a, b) => b.lastSeenMinutesAgo - a.lastSeenMinutesAgo,
                    },
                ]}
                dataSource={rows}
                defaultSorting={{ columnKey: 'count', order: -1 }}
                rowKey="value"
                size="small"
            />
        </div>
    )
}
