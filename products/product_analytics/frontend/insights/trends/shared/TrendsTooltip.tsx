import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { DefaultTooltip, type TooltipContext } from '@posthog/quill-charts'

import { percentage } from 'lib/utils/numbers'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import {
    getDatumTitle,
    getFormattedDate,
    getTooltipTitle,
    SeriesDatum,
} from 'scenes/insights/InsightTooltip/insightTooltipUtils'
import { formatAggregationValue } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter, CurrencyCode, DateRange, TrendsFilter } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import type { TrendsSeriesMeta } from './trendsSeriesMeta'

type TrendsTooltipEntry = TooltipContext<TrendsSeriesMeta>['seriesData'][number]

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
     *  is an interval-count integer, not a date — letting it format as a calendar date
     *  produces a wrong "Thursday, 1 Jan 1970" header. */
    altTitle?: string | ((tooltipData: SeriesDatum[], formattedDate: string) => React.ReactNode)
    /** Overrides the default value formatter — needed for the pie chart, which renders the
     *  raw aggregation plus the slice's share of the total. */
    renderCount?: (value: number) => string
    /** Overrides the default row label — used by lifecycle, where the label is the lifecycle
     *  status (e.g. "New") rather than the entity name. */
    renderSeriesOverride?: (datum: SeriesDatum) => React.ReactNode
}

/** Renders hog-charts' DefaultTooltip for trends-family charts (trends, stickiness, lifecycle, pie)
 *  so they share the same tooltip surface as SQL insights. Maps the quill TooltipContext to the
 *  insight-flavored value/label/date formatting and wires the per-series persons-modal drill-down. */
export function TrendsTooltip({
    context,
    timezone = 'UTC',
    interval,
    breakdownFilter,
    dateRange,
    trendsFilter,
    showPercentView,
    isPercentStackView,
    baseCurrency,
    groupTypeLabel = 'people',
    formatCompareLabel,
    onRowClick,
    showHeader,
    altTitle,
    renderCount: renderCountOverride,
    renderSeriesOverride,
}: TrendsTooltipProps): React.ReactElement {
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { weekStartDay } = useValues(teamLogic)

    // Map each quill series entry (keyed by series.key) to the InsightTooltip SeriesDatum shape so the
    // existing breakdown/compare/value formatting helpers stay reusable. `datasetIndex` mirrors the
    // entry's position in context.seriesData, which the chart's onRowClick maps back to a series key.
    const datumByKey = useMemo(() => {
        const m = new Map<string, SeriesDatum>()
        context.seriesData.forEach((entry, idx) => {
            const meta = entry.series.meta ?? {}
            m.set(entry.series.key, {
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
            })
        })
        return m
    }, [context.seriesData, context.dataIndex])

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
            // hog-charts passes each segment as a 0..1 fraction, so format it directly as a percentage.
            return percentage(value)
        },
        [renderCountOverride, showPercentView, isPercentStackView, trendsFilter, baseCurrency]
    )

    const valueFormatter = useCallback(
        (value: number, entry: TrendsTooltipEntry): React.ReactNode => {
            const datum = datumByKey.get(entry.series.key)
            return formatAggregationValue(
                datum?.action?.math_property,
                value,
                renderCount,
                formatPropertyValueForDisplay
            )
        },
        [datumByKey, renderCount, formatPropertyValueForDisplay]
    )

    // Multiple distinct events in the tooltip — prefix breakdown rows with the event name
    // so the user knows which series each breakdown value belongs to.
    const hasMultipleEvents = useMemo(() => {
        const events = new Set([...datumByKey.values()].map((d) => d.action?.event ?? d.action?.name))
        return events.size > 1
    }, [datumByKey])

    const labelRenderer = useCallback(
        (entry: TrendsTooltipEntry): React.ReactNode => {
            const datum = datumByKey.get(entry.series.key)
            if (!datum) {
                return entry.series.label
            }
            if (renderSeriesOverride) {
                return renderSeriesOverride(datum)
            }
            const hasBreakdown = datum.breakdown_value !== undefined && !!datum.breakdown_value
            if (hasBreakdown || datum.compare_label) {
                const title = getDatumTitle(datum, breakdownFilter, formatCompareLabel)
                if (hasMultipleEvents && hasBreakdown) {
                    const seriesName = datum.action?.custom_name || datum.action?.name || datum.label
                    return (
                        <>
                            <span className="opacity-50 mr-1 shrink-0">{seriesName} ·</span>
                            {title}
                        </>
                    )
                }
                return title
            }
            return datum.label
        },
        [datumByKey, renderSeriesOverride, breakdownFilter, formatCompareLabel, hasMultipleEvents]
    )

    const labelFormatter = useCallback((): React.ReactNode => {
        const firstKey = context.seriesData[0]?.series.key
        const date = firstKey ? datumByKey.get(firstKey)?.date_label : undefined
        const formattedDate = getFormattedDate(date, { interval, dateRange, timezone, weekStartDay })
        if (altTitle) {
            return getTooltipTitle([...datumByKey.values()], altTitle, formattedDate) ?? formattedDate
        }
        return formattedDate
    }, [context.seriesData, datumByKey, interval, dateRange, timezone, weekStartDay, altTitle])

    const onRowClickEntry = useCallback(
        (entry: TrendsTooltipEntry): void => {
            const datum = datumByKey.get(entry.series.key)
            if (datum) {
                onRowClick?.(datum)
            }
        },
        [datumByKey, onRowClick]
    )

    return (
        <DefaultTooltip<TrendsSeriesMeta>
            {...context}
            sortedByValue
            showHeader={showHeader !== false}
            labelFormatter={labelFormatter}
            labelRenderer={labelRenderer}
            valueFormatter={valueFormatter}
            onRowClick={onRowClick ? onRowClickEntry : undefined}
            footer={
                onRowClick
                    ? context.seriesData.length > 1
                        ? `Click a series to view ${groupTypeLabel}`
                        : `Click to view ${groupTypeLabel}`
                    : undefined
            }
        />
    )
}
