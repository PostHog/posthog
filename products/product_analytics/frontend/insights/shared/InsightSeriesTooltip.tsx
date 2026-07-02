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
import { formatAggregationValue, getDisplayNameFromEntityFilter } from 'scenes/insights/utils'
import { teamLogic } from 'scenes/teamLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter, CurrencyCode, DateRange, TrendsFilter } from '~/queries/schema/schema-general'
import { ActionFilter, IntervalType } from '~/types'

// ── Types ──────────────────────────────────────────────────────────────────

type InsightSeriesMetaBase = {
    action?: ActionFilter
    breakdown_value?: string | number | string[] | null
    compare_label?: SeriesDatum['compare_label']
    days?: string[]
    order?: number
    filter?: SeriesDatum['filter']
}

type InsightSeriesTooltipEntry<Meta extends InsightSeriesMetaBase> = TooltipContext<Meta>['seriesData'][number]

export interface InsightSeriesTooltipProps<Meta extends InsightSeriesMetaBase> {
    context: TooltipContext<Meta>
    timezone?: string
    interval?: IntervalType
    breakdownFilter?: BreakdownFilter
    dateRange?: DateRange
    trendsFilter?: TrendsFilter | null
    showPercentView?: boolean
    isPercentStackView?: boolean
    baseCurrency?: CurrencyCode
    groupTypeLabel?: string
    formatCompareLabel?: (label: string, dateLabel?: string) => string
    onRowClick?: (datum: SeriesDatum) => void
    showHeader?: boolean
    /** Override the auto-derived date header — stickiness passes an interval-count integer
     *  rather than a date, so the default calendar formatter would produce the wrong label. */
    altTitle?: string | ((tooltipData: SeriesDatum[], formattedDate: string) => React.ReactNode)
    /** Override the value formatter — pie chart passes slice share alongside the raw count. */
    renderCount?: (value: number) => string
    /** Override the row label — lifecycle uses the status name rather than the event name. */
    renderSeriesOverride?: (datum: SeriesDatum) => React.ReactNode
    /** Sort rows by value descending. Pass false to preserve visual top-to-bottom order. */
    sortedByValue?: boolean
    /** Hide rows whose value is exactly 0 (e.g. absent lifecycle statuses). */
    hideZeroRows?: boolean
}

// ── Pure helpers ───────────────────────────────────────────────────────────

/** Format a single row's value given the chart's display mode. */
function formatRowValue(
    value: number,
    opts: {
        override?: (value: number) => string
        showPercentView?: boolean
        isPercentStackView?: boolean
        trendsFilter?: TrendsFilter | null
        baseCurrency?: CurrencyCode
    }
): string {
    if (opts.override) {
        return opts.override(value)
    }
    if (opts.showPercentView) {
        return `${value.toFixed(1)}%`
    }
    if (opts.isPercentStackView) {
        // quill-charts delivers percent-stack segments as 0..1 fractions.
        return percentage(value)
    }
    return formatAggregationAxisValue(opts.trendsFilter, value, opts.baseCurrency)
}

// ── SeriesLabel ────────────────────────────────────────────────────────────

interface SeriesLabelProps {
    datum: SeriesDatum
    breakdownFilter?: BreakdownFilter
    formatCompareLabel?: (label: string, dateLabel?: string) => string
    hasMultipleEvents: boolean
    renderSeriesOverride?: (datum: SeriesDatum) => React.ReactNode
}

/**
 * Label for a single tooltip row. Handles four cases:
 *   1. Custom override (lifecycle status, etc.)
 *   2. Breakdown + compare — breakdown truncates; period label is always fully visible
 *   3. Breakdown or compare alone — same split layout
 *   4. Plain series label
 */
export function SeriesLabel({
    datum,
    breakdownFilter,
    formatCompareLabel,
    hasMultipleEvents,
    renderSeriesOverride,
}: SeriesLabelProps): React.ReactNode {
    if (renderSeriesOverride) {
        return renderSeriesOverride(datum)
    }

    const hasBreakdown =
        datum.breakdown_value !== undefined && datum.breakdown_value !== null && datum.breakdown_value !== ''

    if (!hasBreakdown && !datum.compare_label) {
        return datum.label
    }

    const comparePeriod = datum.compare_label
        ? formatCompareLabel
            ? formatCompareLabel(String(datum.compare_label), datum.date_label)
            : datum.compare_label === 'current'
              ? 'Current'
              : 'Previous'
        : null

    const breakdownTitle = hasBreakdown
        ? getDatumTitle({ ...datum, compare_label: undefined }, breakdownFilter, formatCompareLabel)
        : null

    const eventPrefix = hasMultipleEvents ? (
        <span className="opacity-50 mr-1 shrink-0">
            {(datum.action ? getDisplayNameFromEntityFilter(datum.action) : null) ?? datum.label} ·
        </span>
    ) : null

    // inline-flex: breakdown span truncates (flex-1), period label stays visible (shrink-0).
    return (
        <span className="inline-flex items-center w-full overflow-hidden">
            {eventPrefix}
            <span className="truncate min-w-0 flex-1">{breakdownTitle ?? datum.label}</span>
            {comparePeriod && <span className="shrink-0 opacity-60">&nbsp;·&nbsp;{comparePeriod}</span>}
        </span>
    )
}

// ── InsightSeriesTooltip ───────────────────────────────────────────────────

/** DefaultTooltip adapter for insight series charts (trends, retention, stickiness).
 *  Maps the quill TooltipContext to insight-flavored value/label/date formatting and
 *  wires persons-modal drill-down via onRowClick. */
export function InsightSeriesTooltip<Meta extends InsightSeriesMetaBase>({
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
    renderCount,
    renderSeriesOverride,
    sortedByValue = true,
    hideZeroRows,
}: InsightSeriesTooltipProps<Meta>): React.ReactElement {
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { weekStartDay } = useValues(teamLogic)

    // Quill delivers one entry per series key; map to SeriesDatum so existing
    // formatting helpers (getDatumTitle, formatAggregationValue, etc.) stay reusable.
    const datumByKey = useMemo(() => {
        const m = new Map<string, SeriesDatum>()
        context.seriesData.forEach((entry, idx) => {
            const meta = (entry.series.meta ?? {}) as InsightSeriesMetaBase
            m.set(entry.series.key, {
                id: idx,
                dataIndex: context.dataIndex,
                datasetIndex: idx,
                order: meta.order ?? idx,
                label: entry.series.label,
                color: entry.color,
                count: entry.value,
                action: meta.action,
                breakdown_value: meta.breakdown_value ?? undefined,
                compare_label: meta.compare_label,
                date_label: meta.days?.[context.dataIndex],
                filter: meta.filter,
            })
        })
        return m
    }, [context.seriesData, context.dataIndex])

    const hasMultipleEvents = useMemo(() => {
        const events = new Set([...datumByKey.values()].map((d) => d.action?.id ?? d.action?.name))
        return events.size > 1
    }, [datumByKey])

    const valueFormatter = useCallback(
        (value: number, entry: InsightSeriesTooltipEntry<Meta>): React.ReactNode => {
            const datum = datumByKey.get(entry.series.key)
            return formatAggregationValue(
                datum?.action?.math_property,
                value,
                (v) =>
                    formatRowValue(v, {
                        override: renderCount,
                        showPercentView,
                        isPercentStackView,
                        trendsFilter,
                        baseCurrency,
                    }),
                formatPropertyValueForDisplay
            )
        },
        [
            datumByKey,
            renderCount,
            showPercentView,
            isPercentStackView,
            trendsFilter,
            baseCurrency,
            formatPropertyValueForDisplay,
        ]
    )

    const labelRenderer = useCallback(
        (entry: InsightSeriesTooltipEntry<Meta>): React.ReactNode => {
            const datum = datumByKey.get(entry.series.key)
            if (!datum) {
                return entry.series.label
            }
            return (
                <SeriesLabel
                    datum={datum}
                    breakdownFilter={breakdownFilter}
                    formatCompareLabel={formatCompareLabel}
                    hasMultipleEvents={hasMultipleEvents}
                    renderSeriesOverride={renderSeriesOverride}
                />
            )
        },
        [datumByKey, breakdownFilter, formatCompareLabel, hasMultipleEvents, renderSeriesOverride]
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
        (entry: InsightSeriesTooltipEntry<Meta>): void => {
            const datum = datumByKey.get(entry.series.key)
            if (datum) {
                onRowClick?.(datum)
            }
        },
        [datumByKey, onRowClick]
    )

    return (
        <DefaultTooltip<Meta>
            {...context}
            sortedByValue={sortedByValue}
            hideZeroRows={hideZeroRows}
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
