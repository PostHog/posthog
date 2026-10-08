import { useValues } from 'kea'
import { useMemo } from 'react'

import { Heatmap } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import type { MetricsHistogramQueryResponse } from '~/queries/schema/schema-general'

import { formatMetricValue } from './metricsUnits'

/** A latency-over-time heatmap: x = time bucket, y = histogram bucket upper bound, cell =
 * observation count. `yLabels[0]` is the bottom row (smallest bucket), so the response's
 * ascending bounds map directly. */
export function HeatmapPanel({
    response,
    unit,
}: {
    response: MetricsHistogramQueryResponse
    unit?: string | undefined
}): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()

    const xLabels = useMemo(
        () => (response.times ?? []).map((t) => dayjs(t).tz(timezone).format('D MMM HH:mm')),
        [response.times, timezone]
    )
    const yLabels = useMemo(
        () => (response.bounds ?? []).map((b) => formatMetricValue(b, unit)),
        [response.bounds, unit]
    )
    const cells = useMemo(() => response.counts ?? [], [response.counts])

    const hasData = cells.some((row) => row.some((c) => c > 0))
    if (!hasData) {
        return (
            <div className="flex h-full items-center justify-center text-secondary text-sm">
                No data for this metric in the selected range.
            </div>
        )
    }

    return (
        <div className="relative flex h-full w-full min-h-0 flex-col">
            <Heatmap
                xLabels={xLabels}
                yLabels={yLabels}
                cells={cells}
                theme={theme}
                tooltip={(ctx) => {
                    const col = ctx.dataIndex
                    return <span>{xLabels[col]}</span>
                }}
            />
        </div>
    )
}
