import { LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { TrunkQuarantinedTestRow } from '../scenes/engineeringAnalyticsLogic'

function RelativeTime({ iso }: { iso: string }): JSX.Element {
    return (
        <Tooltip title={dayjs(iso).format('YYYY-MM-DD HH:mm:ss')}>
            <span className="text-xs whitespace-nowrap text-secondary">{dayjs(iso).fromNow()}</span>
        </Tooltip>
    )
}

/** One team's quarantined tests, rendered inside the debt table's expanded row. */
export function TeamQuarantinedTestsTable({
    tests,
    ttlDays,
}: {
    tests: TrunkQuarantinedTestRow[]
    ttlDays: number
}): JSX.Element {
    const columns: LemonTableColumns<TrunkQuarantinedTestRow> = [
        {
            title: 'Test',
            key: 'nodeid',
            render: (_, row) => (
                <Tooltip title={row.nodeid}>
                    <span className="block max-w-full truncate font-mono text-xs">{row.nodeid}</span>
                </Tooltip>
            ),
        },
        {
            title: 'Runner',
            key: 'runner',
            width: 90,
            render: (_, row) => row.runner,
        },
        {
            title: 'Quarantined',
            key: 'quarantinedAt',
            width: 130,
            render: (_, row) => <RelativeTime iso={row.quarantinedAt} />,
        },
        {
            title: 'Age',
            key: 'ageDays',
            width: 140,
            align: 'right',
            render: (_, row) => (
                <div className="flex items-center justify-end gap-2">
                    <span>{pluralize(row.ageDays, 'day')}</span>
                    {row.overdue && (
                        <Tooltip
                            title={`Quarantined longer than ${pluralize(ttlDays, 'day')}. Fix the test or delete it.`}
                        >
                            <LemonTag type="danger" size="small">
                                Overdue
                            </LemonTag>
                        </Tooltip>
                    )}
                </div>
            ),
        },
    ]
    return (
        <LemonTable
            data-attr="engineering-analytics-trunk-debt-tests-table"
            size="small"
            embedded
            columns={columns}
            dataSource={tests}
            rowKey={(row) => `${row.runner}:${row.nodeid}`}
            useURLForSorting={false}
            nouns={['test', 'tests']}
        />
    )
}
