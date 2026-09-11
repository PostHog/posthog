import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { ChartDisplayType } from '~/types'

import { RetentionBarChart } from './RetentionBarChart/RetentionBarChart'
import { retentionGraphLogic } from './retentionGraphLogic'
import { RetentionLineChart } from './RetentionLineChart/RetentionLineChart'

interface RetentionGraphProps {
    inSharedMode?: boolean
}

export function RetentionGraph({ inSharedMode = false }: RetentionGraphProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(retentionGraphLogic(insightProps))

    const isBarDisplay = retentionFilter?.display === ChartDisplayType.ActionsBar
    if (isBarDisplay) {
        return <RetentionBarChart inSharedMode={inSharedMode} />
    }
    return <RetentionLineChart inSharedMode={inSharedMode} />
}
