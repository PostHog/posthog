import { useActions, useValues } from 'kea'
import { CSSProperties, ReactNode } from 'react'

import { Button, Checkbox, TableHead } from '@posthog/quill'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownType } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'

import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'

import { CALC_COLUMN_LABELS } from './columns/AggregationColumn'
import { QuillAggregationMenu } from './columns/QuillAggregationMenu'
import { QuillColumnSortButton } from './columns/QuillColumnSortButton'
import { QuillPinColumnButton } from './columns/QuillPinColumnButton'
import { QuillValueColumnTitle } from './columns/QuillValueColumnTitle'
import { AggregationType, insightsTableDataLogic } from './insightsTableDataLogic'
import { InsightsTableColumn, InsightsTableModel, MAX_VALUE_COLUMNS, isNumericColumn } from './useInsightsTableModel'

interface QuillInsightsTableHeadProps {
    column: InsightsTableColumn
    model: InsightsTableModel
    sorting: Sorting | null
    onSort: (columnKey: string) => void
    checkboxDisabledReason?: string
    sticky?: 'left'
    style?: CSSProperties
}

export function QuillInsightsTableHead({
    column,
    model,
    sorting,
    onSort,
    checkboxDisabledReason,
    sticky,
    style,
}: QuillInsightsTableHeadProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        indexedResults,
        isNonTimeSeriesDisplay,
        compareFilter,
        isStickiness,
        interval,
        breakdownFilter,
        getTrendsHidden,
        insightData,
    } = useValues(trendsDataLogic(insightProps))
    const { toggleAllResultsHidden } = useActions(trendsDataLogic(insightProps))
    const { aggregation, isColumnPinned } = useValues(insightsTableDataLogic(insightProps))
    const { setDetailedResultsAggregationType, toggleColumnPin } = useActions(insightsTableDataLogic(insightProps))
    const { weekStartDay, timezone } = useValues(teamLogic)

    const order = sorting?.columnKey === column.key ? sorting.order : null
    const sort = (): void => onSort(column.key)
    const pinButton = (
        <QuillPinColumnButton isPinned={isColumnPinned(column.key)} onTogglePin={() => toggleColumnPin(column.key)} />
    )

    let content: ReactNode = null
    switch (column.kind) {
        case 'label': {
            const allShown = indexedResults.every((dataset) => !getTrendsHidden(dataset))
            const anyShown = indexedResults.some((dataset) => !getTrendsHidden(dataset))
            content = (
                <>
                    {model.hasCheckboxes && (
                        // The checkbox renders inside a tooltip wrapper, so this span is what lines it up with the label.
                        <span className="mr-3 inline-flex align-middle">
                            <Checkbox
                                aria-label="Show all series"
                                checked={allShown}
                                indeterminate={anyShown && !allShown}
                                onCheckedChange={(checked) => toggleAllResultsHidden(indexedResults, !checked)}
                                disabledReason={checkboxDisabledReason}
                            />
                        </span>
                    )}
                    <QuillColumnSortButton order={order} onClick={sort}>
                        {model.isSingleSeriesWithBreakdown ? (
                            <PropertyKeyInfo
                                disableIcon
                                disablePopover
                                value={
                                    breakdownFilter?.breakdown
                                        ? formatBreakdownType(breakdownFilter)
                                        : extractDisplayLabel(
                                              breakdownFilter?.breakdowns?.[0]?.property?.toString() ?? ''
                                          ) || 'Breakdown Value'
                                }
                            />
                        ) : (
                            'Series'
                        )}
                    </QuillColumnSortButton>
                </>
            )
            break
        }
        case 'breakdown':
            content = (
                <>
                    <QuillColumnSortButton order={order} onClick={sort}>
                        {breakdownFilter && (
                            <PropertyKeyInfo disableIcon disablePopover value={formatBreakdownType(breakdownFilter)} />
                        )}
                    </QuillColumnSortButton>
                    {pinButton}
                </>
            )
            break
        case 'multiple-breakdown':
            content = (
                <>
                    <QuillColumnSortButton order={order} onClick={sort}>
                        <PropertyKeyInfo disableIcon disablePopover value={column.title || 'Breakdown Value'} />
                    </QuillColumnSortButton>
                    {pinButton}
                </>
            )
            break
        case 'world-map':
            content = (
                <QuillColumnSortButton order={order} onClick={sort}>
                    <PropertyKeyInfo disableIcon disablePopover value="$geoip_country_name" />
                </QuillColumnSortButton>
            )
            break
        case 'aggregation':
            content = isNonTimeSeriesDisplay ? (
                <QuillColumnSortButton order={order} onClick={sort}>
                    {CALC_COLUMN_LABELS.total}
                </QuillColumnSortButton>
            ) : (
                <>
                    <QuillAggregationMenu
                        aggregation={aggregation}
                        setAggregationType={(state) => setDetailedResultsAggregationType(state as AggregationType)}
                    />
                    <QuillColumnSortButton
                        order={order}
                        onClick={sort}
                        aria-label={`Sort by ${CALC_COLUMN_LABELS[aggregation].toLowerCase()}`}
                    />
                </>
            )
            break
        case 'percent-of-total':
            content = (
                <QuillColumnSortButton order={order} onClick={sort}>
                    % of total
                </QuillColumnSortButton>
            )
            break
        case 'previous':
            content = (
                <QuillColumnSortButton order={order} onClick={sort}>
                    {`Previous ${CALC_COLUMN_LABELS[aggregation]}`}
                </QuillColumnSortButton>
            )
            break
        case 'value':
            content = (
                <QuillColumnSortButton order={order} onClick={sort}>
                    {isStickiness ? (
                        `${interval ? interval.charAt(0).toUpperCase() + interval.slice(1) : 'Day'} ${column.index + 1}`
                    ) : (
                        <QuillValueColumnTitle
                            index={column.index}
                            indexedResults={indexedResults}
                            compare={compareFilter?.compare}
                            interval={interval}
                            resolvedDateRange={insightData?.resolved_date_range}
                            timezone={timezone}
                            weekStartDay={weekStartDay}
                        />
                    )}
                </QuillColumnSortButton>
            )
            break
        case 'load-more':
            content = (
                <Button variant="outline" size="xs" onClick={model.showMoreColumns}>
                    +{Math.min(column.hiddenCount, MAX_VALUE_COLUMNS).toLocaleString()} columns
                </Button>
            )
            break
    }

    return (
        <TableHead
            data-column-key={column.key}
            align={isNumericColumn(column) ? 'right' : undefined}
            aria-sort={order === 1 ? 'ascending' : order === -1 ? 'descending' : undefined}
            className="max-w-80"
            sticky={sticky}
            style={style}
        >
            {content}
        </TableHead>
    )
}
