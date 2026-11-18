import { useMemo } from 'react'

import { LineChart, type LineChartConfig, type Series } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

export function ReleaseMetricSparkline({ values, labels }: { values: number[]; labels: string[] }): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo<Series[]>(
        () => [{ key: 'metric', label: 'Value', data: values, fill: { opacity: 0.12 } }],
        [values]
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
            margins: { top: 4, right: 0, bottom: 0, left: 0 },
            tooltip: { enabled: true, placement: 'follow-data' },
        }),
        []
    )
    return <LineChart series={series} labels={labels} theme={theme} config={config} className="h-full w-full" />
}
