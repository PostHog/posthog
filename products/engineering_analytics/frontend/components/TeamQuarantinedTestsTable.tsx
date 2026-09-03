import { LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { githubFileUrl } from '../lib/github'
import { TrunkQuarantinedTestRow } from '../scenes/engineeringAnalyticsLogic'
import { TestIdCell } from './TestIdCell'

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
            className: 'w-full max-w-0',
            render: (_, row) => {
                // A test the repository could not place carries no file path to link to.
                const url = row.trunkUrl ?? (row.file ? githubFileUrl(repository, row.file) : null)
                return (
                    <TestIdCell
                        nodeid={row.nodeid}
                        url={url}
                        tooltip={row.trunkUrl ? `${row.nodeid} - open in Trunk` : row.nodeid}
                    />
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
