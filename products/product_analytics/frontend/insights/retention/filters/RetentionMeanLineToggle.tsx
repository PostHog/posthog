import { useActions, useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { DisplayOptionCheckbox } from '~/queries/nodes/InsightViz/DisplayOptionCheckbox'

import { retentionGraphLogic } from '../retentionGraphLogic'

export function RetentionMeanLineToggle(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { hasValidBreakdown } = useValues(retentionGraphLogic(insightProps))

    if (!canEditInsight) {
        return null
    }

    const selectedInterval = retentionFilter?.selectedInterval ?? null
    const disabledReason =
        selectedInterval !== null
            ? 'Mean line is not available when viewing a single interval.'
            : hasValidBreakdown
              ? 'Mean line is not available with a breakdown applied.'
              : undefined

    return (
        <DisplayOptionCheckbox
            label="Show mean line"
            checked={!disabledReason && !!retentionFilter?.showMeanLine}
            onChange={(showMeanLine) => updateInsightFilter({ showMeanLine })}
            disabledReason={disabledReason}
        />
    )
}
