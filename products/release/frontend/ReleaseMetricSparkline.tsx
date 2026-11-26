import { useMemo } from 'react'

import { AnomalyPointsLayer, LineChart, type LineChartConfig, ReferenceLine, type Series } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import type { GoalStatus } from './releaseGoals'

const RECENT_POINTS = 7

const STATUS_COLOR: Record<GoalStatus, string> = {
    met: '--success',
    on_track: '--success',
    behind: '--danger',
    no_goal: '--color-text-primary',
    unmeasured: '--color-text-primary',
}

export function ReleaseMetricSparkline({
    values,
    labels,
    status,
    target,
}: {
    values: number[]
    labels: string[]
    status: GoalStatus
    target: number | null
}): JSX.Element {
    const theme = useChartTheme()
    const [tone, line] = useMemo(() => {
        const styles = getComputedStyle(document.body)
        return [
            styles.getPropertyValue(STATUS_COLOR[status]).trim() || theme.colors[0],
            styles.getPropertyValue('--border').trim() || theme.colors[0],
        ]
    }, [status, theme])
    const last = values.length - 1
    const from = Math.max(0, last - RECENT_POINTS)
    const series = useMemo<Series[]>(
        () => [
            { key: 'metric', label: 'Value', data: values, color: line },
            {
                key: 'recent',
                label: 'Recent',
                data: values.map((value, index) => (index >= from ? value : NaN)),
                color: tone,
                visibility: { tooltip: false },
            },
            ...(target === null
                ? []
                : [
                      {
                          key: 'target',
                          label: 'Target',
                          data: values.map(() => target),
                          color: 'transparent',
                          visibility: { tooltip: false },
                      },
                  ]),
        ],
        [values, from, tone, line, target]
    )
    const config = useChartConfig<LineChartConfig>(
        () => ({
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            showCrosshair: true,
            curve: 'linear',
            floatBaseline: true,
            margins: { top: 4, right: 4, bottom: 4, left: 1 },
            tooltip: { enabled: true, placement: 'follow-data' },
        }),
        []
    )
    return (
        <LineChart series={series} labels={labels} theme={theme} config={config} className="h-full w-full">
            {target !== null && <ReferenceLine value={target} variant="marker" showValueOnHover={false} />}
            <AnomalyPointsLayer
                radius={2.5}
                markers={last >= 0 ? [{ dataIndex: last, value: values[last], color: tone, yAxisId: 'left' }] : []}
            />
        </LineChart>
    )
}
