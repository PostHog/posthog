import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export type RetentionMeanType = 'simple' | 'weighted'

export function RetentionMeanDropdown(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const meanRetentionCalculation = retentionFilter?.meanRetentionCalculation ?? 'simple'

    if (!canEditInsight) {
        return null
    }

    return (
        <LemonSelect
            className="w-48"
            size="small"
            value={meanRetentionCalculation}
            onChange={(meanRetentionCalculation) => {
                updateInsightFilter({ meanRetentionCalculation })
            }}
            options={[
                {
                    value: 'simple',
                    label: 'simple',
                    tooltip:
                        'Calculates the average retention rate across all cohorts by giving equal weight to each cohort, regardless of its size.',
                },
                {
                    value: 'weighted',
                    label: 'weighted',
                    tooltip:
                        'Calculates the average retention rate by giving more weight to larger cohorts, accounting for different cohort sizes in the final mean.',
                },
            ]}
        />
    )
}
