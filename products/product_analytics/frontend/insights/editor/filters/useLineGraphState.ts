import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { ChartDisplayType } from '~/types'

import { displayMatches, isDefaultTrendsLineDisplay, LINE_DISPLAYS } from '../displayTypes'

export function useLineGraphState(): { isLineGraph: boolean; isLinearScale: boolean } {
    const { insightProps } = useValues(insightLogic)
    const { querySource, display, yAxisScaleType } = useValues(insightVizDataLogic(insightProps))
    const isLineDisplay = isDefaultTrendsLineDisplay(display, querySource) || displayMatches(display, LINE_DISPLAYS)
    const isCumulativeLineDisplay = display === ChartDisplayType.ActionsLineGraphCumulative
    return {
        isLineGraph: isLineDisplay && !isCumulativeLineDisplay,
        isLinearScale: !yAxisScaleType || yAxisScaleType === 'linear',
    }
}
