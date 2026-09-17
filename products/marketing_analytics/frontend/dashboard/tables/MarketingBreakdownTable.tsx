import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelectOptionLeaf, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { TileId } from 'scenes/web-analytics/common'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import {
    DASHBOARD_BREAKDOWNS,
    BREAKDOWN_LABELS,
    displayBreakdownValue,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'
import { WebTileHeader } from 'scenes/web-analytics/WebTileHeader'

import { MarketingAnalyticsAttributionBreakdown } from '~/queries/schema/schema-general'

import { marketingDashboardLogic } from '../marketingDashboardLogic'
import { BreakdownTableColumn, compareByCurrent } from './breakdownTableColumn'
import { buildExportMenuItems, buildExportRows } from './breakdownTableExport'
import { ChangeValueCell } from './ChangeValueCell'

export interface MarketingBreakdownTableProps<Row extends Record<string, any>> {
    tileId: TileId
    titlePrefix: string
    rows: Row[]
    rowKey: (row: Row) => string
    breakdownValue: (row: Row) => string
    columns: BreakdownTableColumn<Row>[]
    defaultSortKey: string
    loading: boolean
    error: boolean
    onRetry: () => void
    emptyState: string
    footnote?: React.ReactNode
    exportFilename: string
}

const BREAKDOWN_OPTIONS: LemonSelectOptionLeaf<string>[] = DASHBOARD_BREAKDOWNS.map((breakdown) => ({
    value: breakdown,
    label: BREAKDOWN_LABELS[breakdown],
}))

export function MarketingBreakdownTable<Row extends Record<string, any>>({
    tileId,
    titlePrefix,
    rows,
    rowKey,
    breakdownValue,
    columns,
    defaultSortKey,
    loading,
    error,
    onRetry,
    emptyState,
    footnote,
    exportFilename,
}: MarketingBreakdownTableProps<Row>): JSX.Element {
    const { dashboardBreakdown } = useValues(marketingAnalyticsLogic)
    const { setDashboardBreakdown } = useActions(marketingAnalyticsLogic)
    const { baseCurrency } = useValues(teamLogic)
    const { breakdownLabel, compare, expandedMetric, focusedBreakdownValue } = useValues(marketingDashboardLogic)
    const { setFocusedBreakdownValue } = useActions(marketingDashboardLogic)

    const tableColumns: LemonTableColumn<Row, keyof Row | undefined>[] = [
        {
            title: breakdownLabel,
            key: 'breakdown_value',
            render: (_, row) => {
                const label = displayBreakdownValue(breakdownValue(row), breakdownLabel)
                return (
                    <span className="block truncate" title={label}>
                        {label}
                    </span>
                )
            },
        },
        ...columns.map(
            (column): LemonTableColumn<Row, keyof Row | undefined> => ({
                title: (
                    <span className="whitespace-normal">
                        <span className="hidden @min-[40rem]:inline">{column.title}</span>
                        <span className="@min-[40rem]:hidden">{column.shortTitle ?? column.title}</span>
                    </span>
                ),
                key: column.key,
                align: 'right',
                tooltip: column.tooltip,
                sorter: compareByCurrent(column),
                render: (_, row) => (
                    <ChangeValueCell
                        value={column.value(row)}
                        compare={compare}
                        kind={column.kind}
                        reverseColors={column.reverseColors}
                        neutral={column.neutral}
                        tooltipContent={column.tooltipContent?.(row)}
                        currency={baseCurrency}
                    />
                ),
            })
        ),
    ]

    return (
        <div className="@container border rounded bg-surface-primary flex flex-col">
            <WebTileHeader
                tileId={tileId}
                titlePrefix={titlePrefix}
                titleDropdown={{
                    value: dashboardBreakdown,
                    options: BREAKDOWN_OPTIONS,
                    onChange: (value) => setDashboardBreakdown(value as MarketingAnalyticsAttributionBreakdown),
                }}
                overflowMenuItems={buildExportMenuItems(
                    () =>
                        buildExportRows({
                            columns,
                            rows,
                            breakdownLabel,
                            breakdownValue,
                            compare,
                        }),
                    exportFilename,
                    rows.length > 0
                )}
            />
            {error && !loading ? (
                <div className="p-3">
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: onRetry }}>
                        Couldn't load this table. Try again.
                    </LemonBanner>
                </div>
            ) : (
                <div className="max-h-[36rem] overflow-auto">
                    <LemonTable
                        className="@max-[40rem]:[&_.sorting-indicator]:hidden"
                        embedded
                        tableLayout="fixed"
                        size="small"
                        firstColumnSticky
                        useURLForSorting={false}
                        columns={tableColumns}
                        dataSource={loading ? [] : rows}
                        loading={loading}
                        rowKey={rowKey as (row: Row) => string}
                        defaultSorting={{ columnKey: defaultSortKey, order: -1 }}
                        emptyState={emptyState}
                        onRow={
                            expandedMetric
                                ? (row) => ({
                                      onClick: () =>
                                          setFocusedBreakdownValue(
                                              displayBreakdownValue(breakdownValue(row), breakdownLabel)
                                          ),
                                      className: 'cursor-pointer',
                                      title: 'Focus this line in the chart',
                                  })
                                : undefined
                        }
                        // rowStatus rather than a background class: the first column is sticky and
                        // paints its own background, so a class on the row alone leaves that cell
                        // unhighlighted.
                        rowStatus={(row) =>
                            focusedBreakdownValue &&
                            displayBreakdownValue(breakdownValue(row), breakdownLabel) === focusedBreakdownValue
                                ? 'highlighted'
                                : null
                        }
                    />
                </div>
            )}
            {footnote && <div className="text-secondary text-xs px-3 pb-3">{footnote}</div>}
        </div>
    )
}
