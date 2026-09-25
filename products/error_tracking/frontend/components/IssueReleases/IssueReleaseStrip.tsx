import { useValues } from 'kea'
import { useMemo } from 'react'

import { BarChart } from '@posthog/quill-charts'
import type { BarChartConfig, Series } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

interface IssueReleaseStripProps {
    stripKey: string
    label: string
    color: string
    counts: number[]
    /** ISO bucket starts, aligned with `counts`. */
    buckets: string[]
    /** Shared value ceiling, so bar heights compare across every strip in the panel. */
    maxValue: number
}

export function IssueReleaseStrip({
    stripKey,
    label,
    color,
    counts,
    buckets,
    maxValue,
}: IssueReleaseStripProps): JSX.Element {
    const theme = useChartTheme()
    const { timezone } = useValues(teamLogic)
    const series = useMemo<Series[]>(
        () => [{ key: stripKey, label, color, data: counts }],
        [stripKey, counts, label, color]
    )
    const config = useChartConfig<BarChartConfig>(
        () => ({
            hideXAxis: true,
            hideYAxis: true,
            showGrid: false,
            showAxisLines: false,
            showTickMarks: false,
            showCrosshair: false,
            barCornerRadius: 1,
            margins: { top: 1, right: 0, bottom: 0, left: 0 },
            bars: {
                bandPadding: 0.25,
                minBarSize: 2,
                valueDomain: { min: 0, max: Math.max(1, maxValue) },
            },
            tooltip: {
                placement: 'cursor',
                pinnable: false,
                hitArea: 'band',
                labelFormatter: (bucketLabel) => dayjs(bucketLabel).tz(timezone).format('D MMM YYYY HH:mm'),
                valueFormatter: (value) => `${value} ${value === 1 ? 'occurrence' : 'occurrences'}`,
            },
        }),
        [maxValue, timezone]
    )

    return (
        <div className="flex h-6 w-full min-w-0 overflow-hidden">
            <BarChart
                series={series}
                labels={buckets}
                theme={theme}
                config={config}
                className="h-full"
                dataAttr="error-tracking-issue-release-strip"
            />
        </div>
    )
}
