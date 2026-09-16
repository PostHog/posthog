import { LemonTable, LemonTableColumn, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { displayBreakdownValue } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'
import { VariationCell } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { MarketingAnalyticsRetentionSummaryRow } from '~/queries/schema/schema-general'

const CountCell = VariationCell({ reserveTrendSpace: false })
const RateCell = VariationCell({ isPercentage: true })
const DaysCell = VariationCell({ neutral: true, formatValue: (value) => value.toFixed(1) })

type ReturnRow = MarketingAnalyticsRetentionSummaryRow & { comparison?: MarketingAnalyticsRetentionSummaryRow }

function returnRate(row: MarketingAnalyticsRetentionSummaryRow | undefined, days: 7 | 30): number | null {
    const eligible = days === 7 ? row?.eligible7d : row?.eligible30d
    const returned = days === 7 ? row?.returned7d : row?.returned30d
    return eligible ? (returned ?? 0) / eligible : null
}

export function RetentionReturnTable({
    rows,
    dimensionLabel,
    loading,
    compare,
}: {
    rows: MarketingAnalyticsRetentionSummaryRow[]
    dimensionLabel: string
    loading: boolean
    compare: boolean
}): JSX.Element {
    const previous = new Map(rows.filter((row) => row.previous).map((row) => [row.breakdownValue, row]))
    const current = rows.filter((row) => !row.previous)
    const total = current.reduce((sum, row) => sum + row.acquired, 0)
    const data: ReturnRow[] = current.map((row) => ({ ...row, comparison: previous.get(row.breakdownValue) }))
    const columns: LemonTableColumn<ReturnRow, keyof ReturnRow | undefined>[] = [
        {
            title: dimensionLabel,
            dataIndex: 'breakdownValue',
            render: (_, row) => (
                <span className="block truncate" title={displayBreakdownValue(row.breakdownValue, dimensionLabel)}>
                    {displayBreakdownValue(row.breakdownValue, dimensionLabel)}
                </span>
            ),
        },
        {
            title: (
                <span className="whitespace-normal">
                    <span className="hidden @min-[40rem]:inline">Acquired users</span>
                    <span className="@min-[40rem]:hidden">Users</span>
                </span>
            ),
            key: 'acquired',
            align: 'right',
            tooltip: 'People acquired in the selected date range, attributed to their first qualifying session.',
            sorter: (a, b) => a.acquired - b.acquired,
            render: (_, row) => (
                <Tooltip title={`${percentage(total ? row.acquired / total : 0, 1)} of acquired users`}>
                    <div className="flex flex-col items-end tabular-nums @min-[40rem]:flex-row @min-[40rem]:justify-end @min-[40rem]:gap-3">
                        <CountCell
                            value={[row.acquired, row.comparison?.acquired ?? null]}
                            context={{ compareFilter: { compare: compare && row.comparison !== undefined } }}
                        />
                        <span className="text-secondary text-xs w-12 shrink-0 text-right">
                            {percentage(total ? row.acquired / total : 0, 1)}
                        </span>
                    </div>
                </Tooltip>
            ),
        },
        ...([7, 30] as const).map(
            (days): LemonTableColumn<ReturnRow, keyof ReturnRow | undefined> => ({
                title: (
                    <span className="whitespace-normal">
                        <span className="hidden @min-[40rem]:inline">{`${days}-day return rate`}</span>
                        <span className="@min-[40rem]:hidden">{`${days}d return`}</span>
                    </span>
                ),
                key: `return${days}`,
                align: 'right',
                tooltip: `People with a second session within ${days} days of acquisition. Only users who have had the full ${days} days are eligible.`,
                sorter: (a, b) => (returnRate(a, days) ?? -1) - (returnRate(b, days) ?? -1),
                render: (_, row) => {
                    const rate = returnRate(row, days)
                    const eligible = days === 7 ? row.eligible7d : row.eligible30d
                    const returned = days === 7 ? row.returned7d : row.returned30d
                    return rate === null ? (
                        <Tooltip title={`No users have completed ${days} days since acquisition yet.`}>
                            <span className="text-muted">–</span>
                        </Tooltip>
                    ) : (
                        <Tooltip
                            title={`${humanFriendlyNumber(returned)} returned out of ${humanFriendlyNumber(eligible)} eligible users.`}
                        >
                            <div>
                                <RateCell
                                    value={[rate, returnRate(row.comparison, days)]}
                                    context={{
                                        compareFilter: {
                                            compare: compare && returnRate(row.comparison, days) !== null,
                                        },
                                    }}
                                />
                            </div>
                        </Tooltip>
                    )
                },
            })
        ),
        {
            title: <span className="whitespace-normal">Days to return</span>,
            dataIndex: 'medianReturnDays',
            align: 'right',
            tooltip:
                'Median days from the first to the second session, among people observed returning within 30 days. Recent users have had less time to return.',
            sorter: (a, b) => (a.medianReturnDays ?? Infinity) - (b.medianReturnDays ?? Infinity),
            render: (_, row) => (
                <Tooltip
                    title={
                        row.returners
                            ? `Based on ${humanFriendlyNumber(row.returners)} returning users.`
                            : 'No second sessions observed within 30 days.'
                    }
                >
                    <div>
                        {row.medianReturnDays === null ? (
                            <span className="text-muted">–</span>
                        ) : (
                            <DaysCell
                                value={[row.medianReturnDays, row.comparison?.medianReturnDays ?? null]}
                                context={{
                                    compareFilter: { compare: compare && row.comparison?.medianReturnDays != null },
                                }}
                            />
                        )}
                    </div>
                </Tooltip>
            ),
        },
    ]
    return (
        <div className="@container flex flex-col gap-2">
            {compare && <div className="text-secondary text-xs">Compared with the previous acquisition period</div>}
            <LemonTable
                className="@max-[40rem]:[&_.sorting-indicator]:hidden"
                tableLayout="fixed"
                columns={columns}
                dataSource={loading ? [] : data}
                loading={loading}
                rowKey="breakdownValue"
                defaultSorting={{ columnKey: 'acquired', order: -1 }}
                firstColumnSticky
                size="small"
                emptyState='No users match this acquisition period. Widen the date range or turn off "Only new users".'
            />
            <div className="text-secondary text-xs">
                Return rates include only users who completed each window. Days to return includes observed returns
                within 30 days and may change as recent users return.
            </div>
        </div>
    )
}
