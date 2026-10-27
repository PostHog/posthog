import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionToggleGroup } from '~/queries/nodes/InsightViz/DisplayOptionToggleGroup'

export function RetentionCohortLabelStartIndexPicker(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!canEditInsight) {
        return null
    }

    const period = retentionFilter?.period || 'Day'

    return (
        <DisplayOptionToggleGroup
            value={retentionFilter?.cohortLabelStartIndex ?? 0}
            onChange={(value: number) => {
                updateInsightFilter({ cohortLabelStartIndex: value })
            }}
            options={[
                {
                    value: 0,
                    label: `${period} 0`,
                },
                {
                    value: 1,
                    label: `${period} 1`,
                },
            ]}
        />
    )
}
