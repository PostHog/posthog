import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { FollowUpStage, ImpactFollowUpExample } from '../../__mocks__/impactFollowUpConceptMocks'

export function ImpactTrendChart({ example, stage }: { example: ImpactFollowUpExample; stage: FollowUpStage }): JSX.Element {
    const theme = useChartTheme()
    const shownDays = stage === 'planned' ? 0 : stage === 'watching' ? example.elapsedDays : example.windowDays
    const labels = [
        ...example.beforeTrend.map((_, index) => `Before ${example.beforeTrend.length - index}`),
        'Release',
        ...Array.from({ length: example.windowDays }, (_, index) => `Day ${index + 1}`),
    ]
    const series: Series[] = [
        {
            key: 'before',
            label: 'Before',
            data: [...example.beforeTrend, ...Array(example.windowDays + 1).fill(NaN)],
            points: { radius: 3 },
        },
        {
            key: 'after',
            label: 'After release',
            data: [
                ...Array(example.beforeTrend.length + 1).fill(NaN),
                ...example.afterTrend.map((value, index) => (index < shownDays ? value : NaN)),
            ],
            points: { radius: 4 },
        },
    ]

    return (
        <div className="flex min-w-0 flex-col gap-2" aria-label={`${example.chartLabel}, before and after release`}>
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="font-semibold">{example.chartLabel}</span>
                <span className="text-secondary">{example.chartGoalLabel}</span>
            </div>
            <div className="flex h-44 min-w-0 flex-col">
                <TimeSeriesLineChart
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={{
                        xAxis: {
                            tickFormatter: (_, index) =>
                                index === 0 ? 'Before' : index === example.beforeTrend.length ? 'Release' : index === labels.length - 1 ? 'End' : null,
                        },
                        yAxis: { startAtZero: true, showGrid: true },
                        showAxisLines: { x: true, y: false },
                        showCrosshair: true,
                        goalLines:
                            example.chartGoal === null ? [] : [{ value: example.chartGoal, label: example.chartGoalLabel }],
                        tooltip: { pinnable: false },
                    }}
                />
            </div>
        </div>
    )
}
