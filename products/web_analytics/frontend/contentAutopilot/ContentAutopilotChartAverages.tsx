import { ContentAutopilotEngineLabel } from './ContentAutopilotEngineLabel'
import { ContentAutopilotRateBar } from './ContentAutopilotRateBar'
import type { PromptVisibilityMetric } from './promptReport'
import { type EngineVisibilityChart, seriesAverages } from './visibilityChart'

export const ContentAutopilotChartAverages = ({
    chart,
    metric,
    days,
    'data-attr': dataAttr,
}: {
    chart: EngineVisibilityChart
    metric: PromptVisibilityMetric
    days: number
    'data-attr': string
}): JSX.Element => {
    const averages = seriesAverages(chart)
    return (
        <div className="flex flex-col gap-2 p-3" data-attr={`${dataAttr}-averages`}>
            <p className="m-0 text-xs text-muted-foreground">
                {days === 0
                    ? 'No answers in this date range yet.'
                    : 'The first day of checks. The trend chart shows from the second day.'}
            </p>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
                {averages.map(({ engine, average }) => (
                    <li key={engine} className="flex items-center justify-between gap-4">
                        <ContentAutopilotEngineLabel engine={engine} />
                        <span className="w-40">
                            {metric === 'position' ? (
                                <span className="block text-right tabular-nums">
                                    {average === null ? '-' : `#${average.toFixed(1)}`}
                                </span>
                            ) : (
                                <ContentAutopilotRateBar rate={average} />
                            )}
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    )
}
