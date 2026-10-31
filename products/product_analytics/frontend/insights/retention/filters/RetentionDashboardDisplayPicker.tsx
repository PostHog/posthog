import { useActions, useValues } from 'kea'

import { ChartOptionSelect } from 'lib/components/ChartOptions/ChartOptionSelect'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { RetentionDashboardDisplayType } from '~/types'

export function RetentionDashboardDisplayPicker(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const displayType = retentionFilter?.dashboardDisplay || RetentionDashboardDisplayType.TableOnly

    if (!canEditInsight) {
        return null
    }

    return (
        <ChartOptionSelect
            value={displayType}
            onChange={(value) => updateInsightFilter({ dashboardDisplay: value })}
            options={[
                { value: RetentionDashboardDisplayType.TableOnly, label: 'Show table only' },
                { value: RetentionDashboardDisplayType.GraphOnly, label: 'Show graph only' },
                { value: RetentionDashboardDisplayType.All, label: 'Show both' },
            ]}
        />
    )
}
