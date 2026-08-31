import { IconExternal } from '@posthog/icons'
import { LemonTable, LemonTableColumns, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { TrunkQuarantinedTestRow } from '../scenes/engineeringAnalyticsLogic'

/** One team's quarantined tests, rendered inside the debt table's expanded row. */
export function TeamQuarantinedTestsTable({
    tests,
    ttlDays,
    repository,
}: {
    tests: TrunkQuarantinedTestRow[]
    ttlDays: number
    /** 'owner/name' the test file paths are relative to, for the GitHub links. */
    repository: string
}): JSX.Element {
    const columns: LemonTableColumns<TrunkQuarantinedTestRow> = [
        {
            title: 'Test',
            key: 'nodeid',
            // max-w-0 lets the auto-layout cell shrink to the distributed width, so a long
            // nodeid truncates instead of pushing the table wider than the scene.
            className: 'w-full max-w-0',
            render: (_, row) => {
                // Rust and Storybook rows carry no file path in Trunk's data.
                const url =
                    row.trunkUrl ?? (row.file ? `https://github.com/${repository}/blob/master/${row.file}` : null)
                if (!url) {
                    return (
                        <Tooltip title={row.nodeid}>
                            <span className="block max-w-full truncate font-mono text-xs">{row.nodeid}</span>
                        </Tooltip>
                    )
                }
                return (
                    <Tooltip title={row.trunkUrl ? `${row.nodeid} - open in Trunk` : row.nodeid}>
                        <Link
                            to={url}
                            target="_blank"
                            targetBlankIcon={false}
                            className="flex max-w-full items-center gap-1 font-mono text-xs"
                        >
                            {/* Icon leads so truncating a long nodeid never clips it away. */}
                            <IconExternal className="shrink-0" />
                            <span className="truncate">{row.nodeid}</span>
                        </Link>
                    </Tooltip>
                )
            },
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
            render: (_, row) => <TZLabel time={row.quarantinedAt} />,
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
