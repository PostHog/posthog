import { useCallback, useMemo } from 'react'

import type { TooltipContext } from '@posthog/quill-charts'

import { hasBreakdown } from 'scenes/funnels/funnelUtils'
import { InsightTooltip } from 'scenes/insights/InsightTooltip/InsightTooltip'
import { getDatumTitle, type SeriesDatum } from 'scenes/insights/InsightTooltip/insightTooltipUtils'

import type { BreakdownFilter, DateRange } from '~/queries/schema/schema-general'
import type { IntervalType } from '~/types'

import { FUNNEL_CONVERSION_SERIES_LABEL, type FunnelSeriesMeta } from '../shared/funnelSeriesMeta'

const NOOP = (): void => {}

interface FunnelLineTooltipProps {
    context: TooltipContext<FunnelSeriesMeta>
    timezone?: string
    interval?: IntervalType
    breakdownFilter?: BreakdownFilter
    dateRange?: DateRange
    groupTypeLabel?: string
    onRowClick?: (datum: SeriesDatum) => void
}

export function FunnelLineTooltip({
    context,
    timezone,
    interval,
    breakdownFilter,
    dateRange,
    groupTypeLabel,
    onRowClick,
}: FunnelLineTooltipProps): React.ReactElement {
    const seriesData = useMemo<SeriesDatum[]>(() => {
        const data = context.seriesData.map((entry, idx) => {
            const meta = entry.series.meta ?? ({} as FunnelSeriesMeta)
            return {
                id: idx,
                dataIndex: context.dataIndex,
                datasetIndex: idx,
                // Each conversion-rate line is a single value, so every series shares one tooltip
                // value column. The inverted layout instead separates them into rows keyed by
                // breakdown_value/compare_label. Distinct orders would split them across columns
                // the layout never renders, leaving every series but the first showing "–".
                order: 0,
                label: entry.series.label,
                color: entry.color,
                count: entry.value,
                breakdown_value: meta.breakdown_value,
                compare_label: meta.compare_label,
                date_label: meta.days?.[context.dataIndex],
            }
        })
        // Order rows by conversion value descending (matching the trends tooltip) so the
        // highest-converting series sits at the top, ties broken alphabetically. datasetIndex
        // keeps the original series index for persons-modal scoping; only the display id is
        // re-derived from the sorted order.
        data.sort(
            (a, b) =>
                b.count - a.count ||
                (a.label === undefined || b.label === undefined ? 0 : a.label.localeCompare(b.label))
        )
        return data.map((s, id) => ({ ...s, id }))
    }, [context.seriesData, context.dataIndex])

    const date = context.seriesData[0]?.series.meta?.days?.[context.dataIndex]

    const renderCount = useCallback((value: number): string => `${value}%`, [])

    const renderSeries = useCallback(
        (_value: React.ReactNode, datum: SeriesDatum): React.ReactElement => {
            if (hasBreakdown(datum.breakdown_value)) {
                return <div className="datum-label-column">{getDatumTitle(datum, breakdownFilter)}</div>
            }
            return <div className="datum-label-column">{FUNNEL_CONVERSION_SERIES_LABEL}</div>
        },
        [breakdownFilter]
    )

    return (
        <InsightTooltip
            date={date}
            timezone={timezone}
            seriesData={seriesData}
            breakdownFilter={breakdownFilter}
            interval={interval}
            dateRange={dateRange}
            groupTypeLabel={groupTypeLabel}
            onClose={context.onUnpin ?? NOOP}
            renderSeries={renderSeries}
            renderCount={renderCount}
            onRowClick={onRowClick}
            hideInspectActorsSection={!onRowClick}
        />
    )
}
