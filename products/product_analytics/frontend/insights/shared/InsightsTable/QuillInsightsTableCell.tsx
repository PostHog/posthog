import { CSSProperties, ReactNode } from 'react'

import { Checkbox, TableCell, cn } from '@posthog/quill'

import { percentage } from 'lib/utils/numbers'
import { ResultSeries } from 'scenes/insights/utils/resultSeries'

import { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter, TrendsFilter } from '~/queries/schema/schema-general'

import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { AggregationColumnItem } from './columns/AggregationColumn'
import { QuillBreakdownValue } from './columns/QuillBreakdownValue'
import { QuillSeriesColorButton } from './columns/QuillSeriesColorButton'
import { QuillSeriesLabel } from './columns/QuillSeriesLabel'
import { formatCompareLabel } from './columns/SeriesColumn'
import { ValueColumnItem } from './columns/ValueColumn'
import { WorldMapColumnItem } from './columns/WorldMapColumn'
import { CalcColumnState, InsightsTableColumn, InsightsTableModel, isNumericColumn } from './useInsightsTableModel'

/** What every cell reads, gathered once by the table so a cell subscribes to nothing. */
export interface QuillInsightsTableCellContext {
    model: InsightsTableModel
    showSwatch: boolean
    canEditSeriesNameInline: boolean
    seriesNameTooltip?: string
    checkboxDisabledReason?: string
    breakdownFilter: BreakdownFilter | null | undefined
    trendsFilter: TrendsFilter | null | undefined
    resultSeries: (item: IndexedTrendResult) => ResultSeries
    isHidden: (item: IndexedTrendResult) => boolean
    toggleResultHidden: (item: IndexedTrendResult) => void
    isNonTimeSeriesDisplay: boolean
    isStickiness: boolean
    aggregation: CalcColumnState
    getPercentOfTotal: (item: IndexedTrendResult) => number | null
    getPreviousResult: (item: IndexedTrendResult) => IndexedTrendResult | undefined
    percentOfDayTotal: ((item: IndexedTrendResult, index: number) => number | null) | null
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction
}

interface QuillInsightsTableCellProps {
    column: InsightsTableColumn
    item: IndexedTrendResult
    context: QuillInsightsTableCellContext
    sticky?: 'left'
    style?: CSSProperties
}

export function QuillInsightsTableCell({
    column,
    item,
    context,
    sticky,
    style,
}: QuillInsightsTableCellProps): JSX.Element {
    const { model, breakdownFilter, trendsFilter, isNonTimeSeriesDisplay, aggregation } = context
    // Formula results synthesized from filler rows can carry compare_label without compare
    const compareValue =
        (item.compare || item.compare_label) && !model.isCompareTable ? formatCompareLabel(item) : undefined

    const swatch = context.showSwatch ? <QuillSeriesColorButton item={item} /> : null

    let content: ReactNode = null
    switch (column.kind) {
        case 'label':
            content = (
                <span className="flex min-w-0 items-center gap-1">
                    {model.hasCheckboxes && (
                        <Checkbox
                            aria-label={`Show ${item.label ?? 'series'}`}
                            checked={!context.isHidden(item)}
                            onCheckedChange={() => context.toggleResultHidden(item)}
                            disabledReason={context.checkboxDisabledReason}
                            className="mr-2"
                        />
                    )}
                    {model.isSingleSeriesWithBreakdown ? (
                        <QuillBreakdownValue
                            label={model.formatItemBreakdownLabel!(item)}
                            breakdownFilter={breakdownFilter}
                            compareValue={compareValue}
                            swatch={swatch}
                        />
                    ) : (
                        <QuillSeriesLabel
                            series={context.resultSeries(item)}
                            fallbackName={item.breakdown_value === '' ? 'None' : item.label}
                            showCountedByTag={model.showCountedByTag}
                            compareValue={compareValue}
                            emphasize={!model.formatItemBreakdownLabel}
                            onRename={
                                context.canEditSeriesNameInline ? () => model.handleSeriesEditClick(item) : undefined
                            }
                            nameTooltip={context.seriesNameTooltip}
                            swatch={swatch}
                        />
                    )}
                </span>
            )
            break
        case 'breakdown':
            content = (
                <QuillBreakdownValue label={model.formatItemBreakdownLabel!(item)} breakdownFilter={breakdownFilter} />
            )
            break
        case 'multiple-breakdown':
            content = <QuillBreakdownValue label={column.formatLabel(item)} breakdownFilter={breakdownFilter} />
            break
        case 'world-map':
            content = <WorldMapColumnItem item={item} />
            break
        case 'aggregation':
            content = (
                <AggregationColumnItem
                    item={item}
                    mathProperty={model.mathPropertyOf(item)}
                    isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                    aggregation={aggregation}
                    trendsFilter={trendsFilter}
                />
            )
            break
        case 'percent-of-total': {
            const share = context.getPercentOfTotal(item)
            content = share === null ? '—' : percentage(share, 1)
            break
        }
        case 'previous': {
            const previousItem = context.getPreviousResult(item)
            content = previousItem ? (
                <AggregationColumnItem
                    item={previousItem}
                    mathProperty={model.mathPropertyOf(previousItem)}
                    isNonTimeSeriesDisplay={isNonTimeSeriesDisplay}
                    aggregation={aggregation}
                    trendsFilter={trendsFilter}
                />
            ) : (
                '—'
            )
            break
        }
        case 'value':
            content = (
                <ValueColumnItem
                    index={column.index}
                    item={item}
                    mathProperty={model.mathPropertyOf(item)}
                    isStickiness={context.isStickiness}
                    renderCount={model.renderCount}
                    formatPropertyValueForDisplay={context.formatPropertyValueForDisplay}
                    percentOfDayTotal={context.percentOfDayTotal?.(item, column.index) ?? null}
                />
            )
            break
    }

    return (
        <TableCell
            align={isNumericColumn(column) ? 'right' : undefined}
            className={cn(isNumericColumn(column) && 'tabular-nums')}
            sticky={sticky}
            style={style}
        >
            {content}
        </TableCell>
    )
}
