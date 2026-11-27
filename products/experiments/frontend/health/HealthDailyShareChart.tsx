import { useValues } from 'kea'
import { useMemo } from 'react'

import { type Series, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { getExperimentVariants } from 'scenes/experiments/utils'
import { teamLogic } from 'scenes/teamLogic'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HEALTH_CHART_MARKER_MARGIN, type HealthChartDayMarker, HealthChartDayMarkers } from './HealthChartDayMarkers'
import { formatHealthPercentage, healthExposureSplit } from './healthCheckValues'
import { healthChangeDays, healthDailyExposures, healthDailyShares, healthVariantColor } from './healthExposureDays'
import { HealthPlannedShareLines } from './HealthPlannedShareLines'

export function HealthDailyShareChart({
    exposures,
    startedOn,
    splitChangedAt,
    showsPlan,
    units,
}: {
    exposures: ExperimentExposureQueryResponse | null
    /** The day the server found the mismatch to start. Null when it was there from the first day. */
    startedOn: string | null
    splitChangedAt: string[]
    /** False after a split change, because the planned lines would show today's split over days that followed an earlier one. */
    showsPlan: boolean
    units: string
}): JSX.Element | null {
    const { timezone } = useValues(teamLogic)
    const { experiment } = useValues(experimentLogic)
    const flagVariants = useMemo(() => getExperimentVariants(experiment), [experiment])
    const theme = useChartTheme()
    const daily = useMemo(() => healthDailyExposures(exposures), [exposures])
    const shares = useMemo(() => (daily ? healthDailyShares(daily) : null), [daily])
    const series = useMemo<Series[]>(
        () =>
            (shares ?? []).map(({ variant, shares }) => ({
                key: variant,
                label: variant,
                data: shares,
                color: healthVariantColor(variant, flagVariants),
            })),
        [shares, flagVariants, theme]
    )
    const planned = useMemo(
        () =>
            showsPlan
                ? (healthExposureSplit(exposures) ?? []).flatMap(({ plannedPercentage }) =>
                      plannedPercentage === null ? [] : [plannedPercentage]
                  )
                : [],
        [exposures, showsPlan]
    )
    const markers = useMemo<HealthChartDayMarker[]>(() => {
        const days = daily?.days ?? []
        return [
            ...healthChangeDays(splitChangedAt, timezone, days).map((day) => ({ day, label: 'Split changed' })),
            ...(startedOn && days.includes(startedOn) ? [{ day: startedOn, label: 'Mismatch starts' }] : []),
        ]
    }, [daily, splitChangedAt, timezone, startedOn])
    const hasMarkers = markers.length > 0
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            ...(hasMarkers ? { margins: { top: HEALTH_CHART_MARKER_MARGIN } } : {}),
            xAxis: { interval: 'day', timezone },
            yAxis: { format: 'percentage', decimalPlaces: 0, startAtZero: true },
            // Keeps a planned line on the chart when every share stays below it.
            valueDomain: { include: planned },
            legend: { show: true },
            tooltip: { placement: 'cursor', valueFormatter: formatHealthPercentage },
        }),
        [timezone, planned, hasMarkers]
    )

    if (!daily || !shares) {
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
                    <HealthPlannedShareLines planned={planned} />
                    <HealthChartDayMarkers markers={markers} />
                </TimeSeriesLineChart>
            </div>
        </div>
    )
}
