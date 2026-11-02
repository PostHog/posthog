import { useActions, useValues } from 'kea'

import { ExcludeOutliersOption } from 'lib/components/ChartOptions/ExcludeOutliersOption'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { isTrendsQuery } from '~/queries/utils'

export function ExcludeOutliersFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))

    return (
        <ExcludeOutliersOption
            checked={trendsFilter?.excludeBoxPlotOutliers !== false}
            onChange={(checked) => {
                if (isTrendsQuery(querySource)) {
                    updateQuerySource({
                        ...querySource,
                        trendsFilter: { ...trendsFilter, excludeBoxPlotOutliers: checked },
                    })
                }
            }}
        />
    )
}
