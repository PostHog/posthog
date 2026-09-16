import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionMeanLineToggle(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!canEditInsight) {
        return null
    }

    return (
        <LemonCheckbox
            className="p-1 px-2"
            checked={!!retentionFilter?.showMeanLine}
            onChange={(showMeanLine) => updateInsightFilter({ showMeanLine })}
            label={<span className="font-normal">Show mean line</span>}
            size="small"
        />
    )
}
