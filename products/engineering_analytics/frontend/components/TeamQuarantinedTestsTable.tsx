import { LemonTable, LemonTableColumns, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { pluralize } from 'lib/utils/strings'

import { githubFileUrl } from '../lib/github'
import { TrunkQuarantinedTestRow } from '../scenes/engineeringAnalyticsLogic'
import { TestIdCell } from './TestIdCell'

/** One team's quarantined tests, shown in the debt table's expanded row and on the team page. */
export function TeamQuarantinedTestsTable({
    tests,
    ttlDays,
    repository,
    loading = false,
}: {
    tests: TrunkQuarantinedTestRow[]
    ttlDays: number
    /** 'owner/name' the test file paths are relative to, for the GitHub links. */
    repository: string
    loading?: boolean
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
            align: 'right',
            sorter: (a, b) => a.quarantinedAt.localeCompare(b.quarantinedAt),
            render: (_, row) => <TZLabel time={row.quarantinedAt} />,
        },
        {
            title: 'Age',
            key: 'ageDays',
            width: 140,
            align: 'right',
            sorter: (a, b) => a.ageDays - b.ageDays,
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
            loading={loading}
            useURLForSorting={false}
            emptyState="No quarantined tests belong to this team."
            nouns={['test', 'tests']}
        />
    )
}
