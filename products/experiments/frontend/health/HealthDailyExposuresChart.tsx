import { useValues } from 'kea'
import { useMemo } from 'react'

import { type Series, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import type { ExperimentExposureQueryResponse } from '~/queries/schema/schema-general'

import { HEALTH_CHART_MARKER_MARGIN, HealthChartDayMarker } from './HealthChartDayMarker'
import { healthFlagChangeTimes } from './healthCheckRows'
import { healthDailyExposures, healthExposureDay } from './healthExposureDays'
import type { HealthPanelCheck } from './healthPanelChecks'

export function HealthDailyExposuresChart({
    check,
    exposures,
    units,
}: {
    /** A check of flag changes, whose rows mark the days of the changes. */
    check: HealthPanelCheck
    exposures: ExperimentExposureQueryResponse | null
    units: string
}): JSX.Element | null {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const daily = useMemo(() => healthDailyExposures(exposures), [exposures])
    const series = useMemo<Series[]>(
        () => (daily?.variants ?? []).map(({ variant, counts }) => ({ key: variant, label: variant, data: counts })),
        [daily]
    )
    const changeDays = useMemo(() => {
        const days = healthFlagChangeTimes(check).map((time) => healthExposureDay(time, timezone))
        return [...new Set(days)].filter((day) => daily?.days.includes(day))
    }, [check, timezone, daily])
    const marksChanges = changeDays.length > 0
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            ...(marksChanges ? { margins: { top: HEALTH_CHART_MARKER_MARGIN } } : {}),
            xAxis: { interval: 'day', timezone },
            legend: { show: true },
            tooltip: { placement: 'cursor' },
        }),
        [timezone, marksChanges]
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
                    {changeDays.map((day) => (
                        <HealthChartDayMarker key={day} day={day} label="Split changed" />
                    ))}
                </TimeSeriesLineChart>
            </div>
        </div>
    )
}
