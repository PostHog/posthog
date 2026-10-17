import './Funnel.scss'

import { useValues } from 'kea'

import { FunnelLayout } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartParams, FunnelVizType } from '~/types'

import { FunnelBarHorizontalChart } from './FunnelBarHorizontalChart/FunnelBarHorizontalChart'
import { FunnelBarListChart } from './FunnelBarListChart/FunnelBarListChart'
import { funnelDataLogic } from './funnelDataLogic'
import { FunnelFlowGraph } from './FunnelFlowGraph/FunnelFlowGraph'
import { FunnelHistogramChart } from './FunnelHistogramChart/FunnelHistogramChart'
import { FunnelLineChart } from './FunnelLineChart/FunnelLineChart'
import { FunnelStepsBarChart } from './FunnelStepsBarChart/FunnelStepsBarChart'

export function Funnel(props: ChartParams): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter, funnelVizType } = useValues(funnelDataLogic(insightProps))
    const { layout } = funnelsFilter || {}
    const showBarList = useFeatureFlag('FUNNEL_BAR_LIST')

    let viz: JSX.Element | null = null
    if (funnelVizType == FunnelVizType.Trends) {
        viz = <FunnelLineChart {...props} />
    } else if (funnelVizType == FunnelVizType.TimeToConvert) {
        viz = <FunnelHistogramChart />
    } else if (funnelVizType === FunnelVizType.Flow) {
        viz = <FunnelFlowGraph />
    } else if ((layout || FunnelLayout.vertical) === FunnelLayout.vertical) {
        viz = <FunnelStepsBarChart {...props} />
    } else {
        viz = showBarList ? <FunnelBarListChart {...props} /> : <FunnelBarHorizontalChart {...props} />
    }

    return (
        <div
            className={`FunnelInsight FunnelInsight--type-${funnelVizType.toLowerCase()}${
                funnelVizType === FunnelVizType.Steps ? '-' + (layout ?? FunnelLayout.vertical) : ''
            }`}
        >
            {viz}
        </div>
    )
}
