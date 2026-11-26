import { useValues } from 'kea'
import { useMemo } from 'react'

import { type Series, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { teamLogic } from 'scenes/teamLogic'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HEALTH_CHART_MARKER_MARGIN, HealthChartDayMarker } from './HealthChartDayMarker'
import { formatHealthPercentage, healthExposureSplit } from './healthCheckValues'
import { healthDailyExposures, healthDailyShares } from './healthExposureDays'

export function HealthDailyShareChart({
    exposures,
    startedOn,
    showsPlan,
    units,
}: {
    exposures: ExperimentExposureQueryResponse | null
    /** The day the server found the mismatch to start. Null when it was there from the first day. */
    startedOn: string | null
    /** False after a split change, because the planned lines would show today's split over days that followed an earlier one. */
    showsPlan: boolean
    units: string
}): JSX.Element | null {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const daily = useMemo(() => healthDailyExposures(exposures), [exposures])
    const series = useMemo<Series[]>(
        () =>
            daily
                ? healthDailyShares(daily).map(({ variant, shares }) => ({
                      key: variant,
                      label: variant,
                      data: shares,
                  }))
                : [],
        [daily]
    )
    const markedDay = startedOn && daily?.days.includes(startedOn) ? startedOn : null
    const config = useChartConfig<TimeSeriesLineChartConfig>(() => {
        const planned = showsPlan
            ? (healthExposureSplit(exposures) ?? []).flatMap(({ plannedPercentage }) =>
                  plannedPercentage === null ? [] : [plannedPercentage]
              )
            : []
        return {
            ...(markedDay ? { margins: { top: HEALTH_CHART_MARKER_MARGIN } } : {}),
            xAxis: { interval: 'day', timezone },
            yAxis: { format: 'percentage', decimalPlaces: 0, startAtZero: true },
            goalLines: [...new Set(planned)].map((percentage) => ({
                value: percentage,
                label: `Planned ${formatHealthPercentage(percentage)}`,
                // The goal line's default color is a fixed dark gray, which a dark theme hides.
                color: 'var(--color-graph-axis-label)',
                showValueOnHover: false,
            })),
            legend: { show: true },
            tooltip: { placement: 'cursor' },
        }
    }, [timezone, exposures, markedDay, showsPlan])

    if (!daily) {
        return null
    }
    return (
        <div className="flex flex-col gap-1">
            <span className="text-xs text-secondary">Share of the {units} first exposed each day, by variant</span>
            <div className="relative flex h-[200px] max-w-xl flex-col">
                <TimeSeriesLineChart
                    series={series}
                    labels={daily.days}
                    theme={theme}
                    config={config}
                    dataAttr="experiment-health-daily-share-chart"
                >
                    {markedDay && <HealthChartDayMarker day={markedDay} label="Mismatch starts" />}
                </TimeSeriesLineChart>
            </div>
        </div>
    )
}
