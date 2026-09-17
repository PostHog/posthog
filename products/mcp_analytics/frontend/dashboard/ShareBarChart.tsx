import { useMemo } from 'react'

import { BarChart, type ChartTheme, type Series, type TooltipContext } from '@posthog/quill-charts'

import { ShareBarLabels, type ShareBarLabel } from './ShareBarLabels'
import { useShareBarChartConfig } from './useShareBarChartConfig'

export interface ShareBarRow<T> extends ShareBarLabel {
    color?: string
    meta: T
}

export function ShareBarChart<T>({
    rows,
    totalCalls,
    theme,
    tooltip,
    label,
}: {
    rows: ShareBarRow<T>[]
    totalCalls: number
    theme: ChartTheme
    tooltip: (ctx: TooltipContext<T & { share: number }>) => JSX.Element | null
    label: string
}): JSX.Element {
    const labels = useMemo(() => rows.map((row) => row.key), [rows])
    const series = useMemo<Series<T & { share: number }>[]>(
        () => [
            {
                key: 'calls',
                label: 'Calls',
                data: rows.map((row) => row.value),
                bars: rows.map((row) => ({
                    label: row.label,
                    color: row.color,
                    meta: { ...row.meta, share: totalCalls > 0 ? (row.value / totalCalls) * 100 : 0 },
                })),
            },
        ],
        [rows, totalCalls]
    )
    const config = useShareBarChartConfig(rows.length, totalCalls)
    return (
        <div className="h-80 overflow-y-auto" translate="no" tabIndex={0} role="region" aria-label={label}>
            <div className="flex min-h-80 flex-col" style={{ height: rows.length * 40 + 20 }}>
                <BarChart series={series} labels={labels} theme={theme} config={config} tooltip={tooltip}>
                    <ShareBarLabels rows={rows} totalCalls={totalCalls} />
                </BarChart>
            </div>
        </div>
    )
}
