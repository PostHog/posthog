import clsx from 'clsx'
import { useValues } from 'kea'

import 'lib/components/InsightLegend/InsightLegend.scss'
import { formatAggregationAxisValue } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import type { IndexedTrendResult } from 'scenes/trends/types'

export interface SlopeGraphLegendProps {
    horizontal?: boolean
    inCardView?: boolean
}

/** The slope graph's legend, rendered in the insight's shared legend slot (like the box plot's) so
 *  it honours the "Show legend" toggle and there's only ever one legend. Each row shows the series
 *  name and its first-to-last change — the slope's readout. */
export function SlopeGraphLegend({ horizontal, inCardView }: SlopeGraphLegendProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { indexedResults, getTrendsColor, getTrendsHidden, trendsFilter } = useValues(trendsDataLogic(insightProps))
    const { baseCurrency } = useValues(teamLogic)

    const visible = (indexedResults ?? []).filter(
        (result: IndexedTrendResult) => !getTrendsHidden(result) && (result.data?.length ?? 0) >= 2
    )

    if (visible.length === 0) {
        return null
    }

    return (
        <div
            className={clsx('InsightLegendMenu', 'flex overflow-auto border rounded', {
                'InsightLegendMenu--horizontal': horizontal,
                'InsightLegendMenu--readonly': true,
                'InsightLegendMenu--in-card-view': inCardView,
            })}
        >
            <div className="grid grid-cols-1">
                {visible.map((result: IndexedTrendResult) => {
                    const delta = result.data[result.data.length - 1] - result.data[0]
                    const change = `${delta >= 0 ? '+' : ''}${formatAggregationAxisValue(trendsFilter, delta, baseCurrency)}`
                    return (
                        <div
                            key={result.id}
                            className="InsightLegendMenu-item p-2 flex flex-row items-center gap-2 whitespace-nowrap"
                        >
                            <span
                                className="w-3 h-3 rounded-full inline-block shrink-0"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ backgroundColor: getTrendsColor(result) }}
                            />
                            <span className="text-xs">{result.label}</span>
                            <span className="text-xs text-secondary ml-auto pl-2">{change}</span>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
