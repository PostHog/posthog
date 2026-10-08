import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonBanner, LemonButton, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'

import { TileId } from 'scenes/web-analytics/common'
import { displayBreakdownValue } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'
import { WebTileHeader, WebTileHeaderProps } from 'scenes/web-analytics/WebTileHeader'

import { CurrencyCode } from '~/queries/schema/schema-general'

import { BreakdownTableColumn, compareByCurrent } from './breakdownTableColumn'
import { buildExportMenuItems, buildExportRows } from './breakdownTableExport'
import { ChangeValueCell } from './ChangeValueCell'
import { marketingBreakdownTableLogic } from './marketingBreakdownTableLogic'

export interface MarketingBreakdownTableProps<Row extends object> {
    tileId: TileId
    titlePrefix: string
    breakdownLabel: string
    titleDropdown?: WebTileHeaderProps['titleDropdown']
    rows: Row[]
    rowKey: (row: Row) => string
    breakdownValue: (row: Row) => string
    columns: BreakdownTableColumn<Row>[]
    defaultSortKey: string
    compare: boolean
    currency: CurrencyCode
    loading: boolean
    error: boolean
    onRetry: () => void
    emptyState: string
    footnote?: React.ReactNode
    exportFilename: string
    focusedBreakdownValue?: string | null
    onFocusBreakdown?: (value: string) => void
}

export function MarketingBreakdownTable<Row extends object>({
    tileId,
    titlePrefix,
    breakdownLabel,
    titleDropdown,
    rows,
    rowKey,
    breakdownValue,
    columns,
    defaultSortKey,
    compare,
    currency,
    loading,
    error,
    onRetry,
    emptyState,
    footnote,
    exportFilename,
    focusedBreakdownValue,
    onFocusBreakdown,
}: MarketingBreakdownTableProps<Row>): JSX.Element {
    const tableKey = useId()
    const logic = marketingBreakdownTableLogic({ tableKey, defaultSortKey })
    const { sorting } = useValues(logic)
    const { setSorting } = useActions(logic)
    const tableColumns: LemonTableColumn<Row, keyof Row | undefined>[] = [
        {
            title: breakdownLabel,
            key: 'breakdown_value',
            render: (_, row) => {
                const value = breakdownValue(row)
                const label = displayBreakdownValue(value, breakdownLabel)
                return onFocusBreakdown ? (
                    <LemonButton
                        size="xsmall"
                        onClick={() => onFocusBreakdown(value)}
                        tooltip="Focus this line in the chart"
                        aria-label={`Focus ${label} in the chart`}
                        data-attr="marketing-breakdown-focus"
                        className="max-w-full"
                    >
                        <span className="truncate" title={label}>
                            {label}
                        </span>
                    </LemonButton>
                ) : (
                    <span className="block truncate" title={label}>
                        {label}
                    </span>
                )
            },
        },
        ...columns.map(
            (column): LemonTableColumn<Row, keyof Row | undefined> => ({
                title: (
                    <span className="whitespace-normal wrap-anywhere">
                        <span className="hidden @min-[40rem]:inline">{column.title}</span>
                        <span className="@min-[40rem]:hidden">
                            {column.shortTitle?.replaceAll('/', '/\u200b') ?? column.title}
                        </span>
                    </span>
                ),
                key: column.key,
                align: 'right',
                tooltip: column.tooltip,
                sorter: compareByCurrent(column, sorting?.order ?? -1),
                render: (_, row) => (
                    <ChangeValueCell
                        value={column.value(row)}
                        compare={compare}
                        kind={column.kind}
                        reverseColors={column.reverseColors}
                        neutral={column.neutral}
                        tooltipContent={column.tooltipContent?.(row)}
                        currency={currency}
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
                title={breakdownLabel}
                titleDropdown={titleDropdown}
                overflowMenuItems={buildExportMenuItems(
                    () =>
                        buildExportRows({
                            columns,
                            rows,
                            breakdownLabel,
                            breakdownValue: (row) => displayBreakdownValue(breakdownValue(row), breakdownLabel),
                            compare,
                            sorting,
                        }),
                    exportFilename,
                    !loading && !error && rows.length > 0
                )}
            />
            {error && !loading ? (
                <div className="p-3">
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Retry',
                            onClick: onRetry,
                            'data-attr': 'marketing-breakdown-table-retry',
                        }}
                    >
                        Couldn't load this table. Try again.
                    </LemonBanner>
                </div>
            ) : (
                <div className="max-h-[36rem] overflow-auto">
                    {/* Cap long breakdowns so later dashboard sections stay within reach. */}
                    <LemonTable
                        className="@max-[40rem]:[&_th_svg]:hidden @max-[40rem]:[&_.sorting-indicator]:hidden"
                        embedded
                        tableLayout="fixed"
                        size="small"
                        firstColumnSticky
                        useURLForSorting={false}
                        columns={tableColumns}
                        dataSource={loading ? [] : rows}
                        loading={loading}
                        loadingSkeletonRows={5}
                        rowKey={rowKey}
                        sorting={sorting}
                        onSort={setSorting}
                        emptyState={emptyState}
                        // The sticky first column paints its own background, so a row class alone leaves it unhighlighted.
                        rowStatus={(row) => (focusedBreakdownValue === breakdownValue(row) ? 'highlighted' : null)}
                    />
                </div>
            )}
            {footnote && <div className="text-secondary text-xs px-3 pb-3">{footnote}</div>}
        </div>
    )
}
