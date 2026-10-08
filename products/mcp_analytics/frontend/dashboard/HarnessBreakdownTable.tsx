import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { formatPercentage } from 'lib/utils/numbers'

import { type HarnessRow } from '../mcpDashboardOverviewLogic'
import { formatNumber } from './formatters'
import { HarnessLogo } from './harness'

export function HarnessBreakdownTable({ rows, totalCalls }: { rows: HarnessRow[]; totalCalls: number }): JSX.Element {
    return (
        <LemonTable<HarnessRow>
            dataSource={rows}
            rowKey="category"
            size="small"
            embedded
            tableLayout="fixed"
            uppercaseHeader={false}
            pagination={{ pageSize: 10, useUrl: false }}
            nouns={['harness', 'harnesses']}
            columns={[
                {
                    title: 'Harness',
                    dataIndex: 'category',
                    render: (_, row) =>
                        row.category === 'Other' ? (
                            <Tooltip title="Clients that could not be classified, including calls with no client identity.">
                                <span tabIndex={0}>Unrecognized harnesses</span>
                            </Tooltip>
                        ) : (
                            <span className="flex items-center gap-1.5">
                                <HarnessLogo category={row.category} />
                                <span className="break-words" translate="no">
                                    {row.category}
                                </span>
                            </span>
                        ),
                },
                {
                    title: 'Calls',
                    dataIndex: 'total_calls',
                    align: 'right',
                    width: 75,
                    render: (_, row) => formatNumber(row.total_calls),
                },
                {
                    title: '% of all calls',
                    align: 'right',
                    width: 100,
                    render: (_, row) =>
                        formatPercentage(totalCalls > 0 ? (row.total_calls / totalCalls) * 100 : 0, { compact: true }),
                },
            ]}
        />
    )
}
