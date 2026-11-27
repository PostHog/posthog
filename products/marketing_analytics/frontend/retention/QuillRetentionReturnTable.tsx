import { useState } from 'react'

import {
    DataTable,
    type DataTableProps,
    Empty,
    EmptyDescription,
    EmptyHeader,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'
import { QuillColumnHeaderTooltip } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/common/QuillColumnHeaderTooltip'
import { QuillTableLoadingRows } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/common/QuillTableLoadingRows'
import { sortQuillTableRows } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/sortQuillTableRows'
import { displayBreakdownValue } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'
import type { VariationCell } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import type { ReturnRowSorter } from './RetentionReturnTable'
import { ReturnRow, returnRate } from './retentionSummary'

type ReturnTableProps = DataTableProps<ReturnRow, unknown>
type ReturnColumn = ReturnTableProps['columns'][number]
type ReturnSorting = NonNullable<ReturnTableProps['sorting']>
type ReturnCell = ReturnType<typeof VariationCell>

// Below 40rem the headers wrap and drop the info icon, so the four columns fit a docked side panel.
const HEADER_TITLE_CLASS = 'text-right leading-tight whitespace-normal'
const HEADER_ICON_CLASS = 'hidden @min-[40rem]:block'

export function QuillRetentionReturnTable({
    data,
    total,
    dimensionLabel,
    loading,
    compare,
    onlyNewUsers,
    sorters,
    cells,
}: {
    data: ReturnRow[]
    total: number
    dimensionLabel: string
    loading: boolean
    compare: boolean
    onlyNewUsers: boolean
    sorters: Record<'acquired' | 'return7' | 'return30' | 'medianReturnDays', ReturnRowSorter>
    cells: { Count: ReturnCell; Rate: ReturnCell; Days: ReturnCell }
}): JSX.Element {
    const [sorting, setSorting] = useState<ReturnSorting>([{ id: 'acquired', desc: true }])
    const sortedData = sortQuillTableRows(data, sorting, sorters)

    const columns: ReturnColumn[] = [
        {
            id: 'breakdownValue',
            header: dimensionLabel,
            enableSorting: false,
            meta: { sticky: 'left' },
            cell: ({ row }) => (
                <span
                    className="block max-w-20 truncate @min-[40rem]:max-w-60"
                    title={displayBreakdownValue(row.original.breakdownValue, dimensionLabel)}
                >
                    {displayBreakdownValue(row.original.breakdownValue, dimensionLabel)}
                </span>
            ),
        },
        {
            id: 'acquired',
            accessorFn: (row: ReturnRow) => row.acquired,
            header: () => (
                <QuillColumnHeaderTooltip
                    title={<span className={HEADER_TITLE_CLASS}>{onlyNewUsers ? 'New users' : 'Users'}</span>}
                    iconClassName={HEADER_ICON_CLASS}
                    tooltip={
                        onlyNewUsers
                            ? 'People whose first qualifying session was in the selected date range.'
                            : 'People with a qualifying session in the selected date range.'
                    }
                />
            ),
            sortDescFirst: false,
            meta: { align: 'right' },
            cell: ({ row }) => (
                <div className="flex flex-col items-end tabular-nums @min-[40rem]:flex-row @min-[40rem]:justify-end @min-[40rem]:gap-3">
                    <span data-not-quill className="contents">
                        <cells.Count
                            value={[row.original.acquired, row.original.comparison?.acquired ?? null]}
                            context={{ compareFilter: { compare: compare && row.original.comparison !== undefined } }}
                            tooltipContent={`${percentage(total ? row.original.acquired / total : 0, 1)} of ${onlyNewUsers ? 'new users' : 'users'}`}
                        />
                    </span>
                    <span className="w-12 shrink-0 text-right text-xs text-muted-foreground">
                        {percentage(total ? row.original.acquired / total : 0, 1)}
                    </span>
                </div>
            ),
        },
        ...([7, 30] as const).map(
            (days): ReturnColumn => ({
                id: `return${days}`,
                accessorFn: (row: ReturnRow) => returnRate(row, days),
                header: () => (
                    <QuillColumnHeaderTooltip
                        title={
                            <span className={HEADER_TITLE_CLASS}>
                                <span className="hidden @min-[40rem]:inline">{`${days}-day return rate`}</span>
                                <span className="@min-[40rem]:hidden">{`${days}d return`}</span>
                            </span>
                        }
                        iconClassName={HEADER_ICON_CLASS}
                        tooltip={`People with a new session on a later calendar day within ${days} days of acquisition, using the project's timezone. Same-day visits do not count. Only users who have had the full ${days} days are eligible.`}
                    />
                ),
                sortDescFirst: false,
                meta: { align: 'right' },
                cell: ({ row }) => {
                    const rate = returnRate(row.original, days)
                    const eligible = days === 7 ? row.original.eligible7d : row.original.eligible30d
                    const returned = days === 7 ? row.original.returned7d : row.original.returned30d
                    return rate === null ? (
                        <Tooltip>
                            <TooltipTrigger render={<span className="text-muted-foreground" />}>–</TooltipTrigger>
                            <TooltipContent>{`No users have completed ${days} days since acquisition yet.`}</TooltipContent>
                        </Tooltip>
                    ) : (
                        <span data-not-quill className="contents">
                            <cells.Rate
                                value={[rate, returnRate(row.original.comparison, days)]}
                                context={{
                                    compareFilter: {
                                        compare: compare && returnRate(row.original.comparison, days) !== null,
                                    },
                                }}
                                tooltipContent={`${humanFriendlyNumber(returned)} returned out of ${humanFriendlyNumber(eligible)} eligible users.`}
                            />
                        </span>
                    )
                },
            })
        ),
        {
            id: 'medianReturnDays',
            accessorFn: (row: ReturnRow) => row.medianReturnDays,
            header: () => (
                <QuillColumnHeaderTooltip
                    title={<span className={HEADER_TITLE_CLASS}>Days to return</span>}
                    iconClassName={HEADER_ICON_CLASS}
                    tooltip="Estimated median calendar days from the first session to the first return on a later day, using the project's timezone. Same-day visits do not count. Includes returns within 30 days. Recent users have had less time to return."
                />
            ),
            sortDescFirst: false,
            meta: { align: 'right' },
            cell: ({ row }) =>
                row.original.medianReturnDays === null ? (
                    <Tooltip>
                        <TooltipTrigger render={<span className="text-muted-foreground" />}>–</TooltipTrigger>
                        <TooltipContent>No returns on a later day observed within 30 days.</TooltipContent>
                    </Tooltip>
                ) : (
                    <span data-not-quill className="contents">
                        <cells.Days
                            value={[row.original.medianReturnDays, row.original.comparison?.medianReturnDays ?? null]}
                            context={{
                                compareFilter: {
                                    compare: compare && row.original.comparison?.medianReturnDays != null,
                                },
                            }}
                            tooltipContent={`Based on ${humanFriendlyNumber(row.original.returners)} returning users.`}
                        />
                    </span>
                ),
        },
    ]

    return (
        <div className="@container flex flex-col gap-2">
            {compare && (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Compared with the previous acquisition period
                </Text>
            )}
            <DataTable
                columns={columns}
                data={loading ? [] : sortedData}
                getRowId={(row) => row.breakdownValue}
                sorting={sorting}
                onSortingChange={setSorting}
                fullWidth
                size="sm"
                empty={
                    loading ? (
                        <QuillTableLoadingRows />
                    ) : (
                        <Empty>
                            <EmptyHeader>
                                <EmptyDescription>
                                    No users match this acquisition period. Widen the date range or turn off "Only new
                                    users".
                                </EmptyDescription>
                            </EmptyHeader>
                        </Empty>
                    )
                }
            />
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Same-day visits do not count. Return rates include only users who completed each window. Days to return
                includes observed returns within 30 days and may change as recent users return.
            </Text>
        </div>
    )
}
