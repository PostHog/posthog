import { useCallback, useMemo } from 'react'

import { SeriesLetter } from 'lib/components/SeriesGlyph'
import type { TooltipContext } from 'lib/hog-charts'
import { percentage } from 'lib/utils'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { getDatumTitle, SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import { BreakdownFilter, CurrencyCode, DateRange, TrendsFilter } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import type { TrendsSeriesMeta } from './trendsSeriesMeta'

const NOOP = (): void => {}

interface TrendsTooltipProps {
    context: TooltipContext<TrendsSeriesMeta>
    timezone?: string
    interval?: IntervalType
    breakdownFilter?: BreakdownFilter
    dateRange?: DateRange
    trendsFilter?: TrendsFilter | null
    formula?: string | null
    showPercentView?: boolean
    isPercentStackView?: boolean
    baseCurrency?: CurrencyCode
    groupTypeLabel?: string
    formatCompareLabel?: (label: string, dateLabel?: string) => string
    onRowClick?: (datum: SeriesDatum) => void
    showHeader?: boolean
    /** Override the auto-derived date header. Stickiness needs this since its `date`
     *  is an interval-count integer, not a date — letting InsightTooltip format it as
     *  a calendar date produces a wrong "Thursday, 1 Jan 1970" header. */
    altTitle?: string | ((tooltipData: SeriesDatum[], formattedDate: string) => React.ReactNode)
    /** Overrides the default value formatter — needed for the pie chart, which renders the
     *  raw aggregation plus the slice's share of the total. */
    renderCount?: (value: number) => string
    // Overrides the default SeriesLetter + InsightLabel row renderer. Mirrors the
    // legacy ActionsLineGraph escape hatch used for lifecycle, where the label
    // is the lifecycle status itself (e.g. "New") and InsightLabel's action.name
    // would otherwise mask it.
    renderSeriesOverride?: (datum: SeriesDatum) => React.ReactNode
}

/** Bridges hog-charts TooltipContext to the legacy InsightTooltip.
 *  Once hog-charts fully replaces Chart.js, we can refactor InsightTooltip
 *  to consume TooltipContext directly and remove this adapter. */
export function TrendsTooltip({
    context,
    timezone,
    interval,
    breakdownFilter,
    dateRange,
    trendsFilter,
    formula,
    showPercentView,
    isPercentStackView,
    baseCurrency,
    groupTypeLabel,
    formatCompareLabel,
    onRowClick,
    showHeader,
    altTitle,
    renderCount: renderCountOverride,
    renderSeriesOverride,
}: TrendsTooltipProps): React.ReactElement {
    const seriesData = useMemo<SeriesDatum[]>(() => {
        const data = context.seriesData.map((entry, idx) => {
            const meta = entry.series.meta ?? {}
            return {
                id: idx,
                dataIndex: context.dataIndex,
                datasetIndex: idx,
                order: meta.order ?? idx,
                label: entry.series.label,
                color: entry.color,
                count: entry.value,
                action: meta.action,
                breakdown_value: meta.breakdown_value,
                compare_label: meta.compare_label,
                date_label: meta.days?.[context.dataIndex],
                filter: meta.filter,
            }
        })
        data.sort(
            (a, b) =>
                b.count - a.count ||
                (a.label === undefined || b.label === undefined ? 0 : a.label.localeCompare(b.label))
        )
        return data.map((s, id) => ({ ...s, id }))
    }, [context.seriesData, context.dataIndex])

    const date = context.seriesData[0]?.series.meta?.days?.[context.dataIndex]

    const renderCount = useCallback(
        (value: number): string => {
            if (renderCountOverride) {
                return renderCountOverride(value)
            }
            if (showPercentView) {
                // Stickiness percent view: value is already a percentage.
                return `${value.toFixed(1)}%`
            }
            if (!isPercentStackView) {
                return formatAggregationAxisValue(trendsFilter, value, baseCurrency)
            }
            // hog-charts passes each segment as a 0..1 fraction (segment_height = top − bottom
            // in expanded-stack space), so format it directly as a percentage.
            return percentage(value)
        },
        [renderCountOverride, showPercentView, isPercentStackView, trendsFilter, baseCurrency]
    )

    const hasMultipleSeries = seriesData.length > 1

    const renderSeries = useCallback(
        (value: React.ReactNode, datum: SeriesDatum): React.ReactElement => {
            if (renderSeriesOverride) {
                return <div className="datum-label-column">{renderSeriesOverride(datum)}</div>
            }
            const hasBreakdown = datum.breakdown_value !== undefined && !!datum.breakdown_value

            if (hasBreakdown && !hasMultipleSeries) {
                const title = getDatumTitle(datum, breakdownFilter, formatCompareLabel)
                return <div className="datum-label-column">{title}</div>
            }

            return (
                <div className="datum-label-column">
                    {!formula && (
                        <SeriesLetter
                            className="mr-2"
                            hasBreakdown={hasBreakdown}
                            seriesIndex={datum.action?.order ?? datum.id}
                            seriesColor={datum.color}
                        />
                    )}
                    {value}
                </div>
            )
        },
        [hasMultipleSeries, breakdownFilter, formatCompareLabel, formula, renderSeriesOverride]
    )

    return (
        <InsightTooltip
            date={date}
            timezone={timezone}
            seriesData={seriesData}
            breakdownFilter={breakdownFilter}
            interval={interval}
            dateRange={dateRange}
            formatCompareLabel={formatCompareLabel}
            groupTypeLabel={groupTypeLabel}
            onClose={context.onUnpin ?? NOOP}
            renderSeries={renderSeries}
            renderCount={renderCount}
            onRowClick={onRowClick}
            hideInspectActorsSection={!onRowClick}
            showHeader={showHeader}
            altTitle={altTitle}
        />
    )
}
