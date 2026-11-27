import { useValues } from 'kea'
import { useMemo } from 'react'

import { type Series, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { getExperimentVariants } from 'scenes/experiments/utils'
import { teamLogic } from 'scenes/teamLogic'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HEALTH_CHART_MARKER_MARGIN, type HealthChartDayMarker, HealthChartDayMarkers } from './HealthChartDayMarkers'
import { healthChangeDays, healthDailyExposures, healthVariantColor } from './healthExposureDays'

export function HealthDailyExposuresChart({
    exposures,
    splitChangedAt,
    units,
}: {
    exposures: ExperimentExposureQueryResponse | null
    splitChangedAt: string[]
    units: string
}): JSX.Element | null {
    const { timezone } = useValues(teamLogic)
    const { experiment } = useValues(experimentLogic)
    const flagVariants = useMemo(() => getExperimentVariants(experiment), [experiment])
    const theme = useChartTheme()
    const daily = useMemo(() => healthDailyExposures(exposures), [exposures])
    const series = useMemo<Series[]>(
        () =>
            (daily?.variants ?? []).map(({ variant, counts }) => ({
                key: variant,
                label: variant,
                data: counts,
                color: healthVariantColor(variant, flagVariants),
            })),
        [daily, flagVariants, theme]
    )
    const markers = useMemo<HealthChartDayMarker[]>(
        () =>
            healthChangeDays(splitChangedAt, timezone, daily?.days ?? []).map((day) => ({
                day,
                label: 'Split changed',
            })),
        [daily, splitChangedAt, timezone]
    )
    const hasMarkers = markers.length > 0
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            ...(hasMarkers ? { margins: { top: HEALTH_CHART_MARKER_MARGIN } } : {}),
            xAxis: { interval: 'day', timezone },
            legend: { show: true },
            tooltip: { placement: 'cursor' },
        }),
        [timezone, hasMarkers]
    )

    if (!daily) {
        return null
    }
    return (
        <div className="flex flex-col gap-1">
            <span className="text-xs text-secondary">
                {capitalizeFirstLetter(units)} first exposed each day, by variant
            </span>
            <div className="relative flex h-[200px] max-w-xl flex-col">
                <TimeSeriesLineChart
                    series={series}
                    labels={daily.days}
                    theme={theme}
                    config={config}
                    dataAttr="experiment-health-daily-exposures-chart"
                >
                    <HealthChartDayMarkers markers={markers} />
                </TimeSeriesLineChart>
            </div>
        </div>
    )
}
