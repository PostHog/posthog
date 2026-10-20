import { useActions, useValues } from 'kea'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import type { RetentionFilter } from '~/queries/schema/schema-general'

export function QuillRetentionMeanDropdown(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    if (!canEditInsight) {
        return null
    }

    return (
        <QuillSelect<NonNullable<RetentionFilter['meanRetentionCalculation']>>
            value={retentionFilter?.meanRetentionCalculation ?? 'simple'}
            onChange={(meanRetentionCalculation) => updateInsightFilter({ meanRetentionCalculation })}
            options={[
                {
                    value: 'simple',
                    label: 'simple',
                    description:
                        'Calculates the average retention rate across all cohorts by giving equal weight to each cohort, regardless of its size.',
                },
                {
                    value: 'weighted',
                    label: 'weighted',
                    description:
                        'Calculates the average retention rate by giving more weight to larger cohorts, accounting for different cohort sizes in the final mean.',
                },
            ]}
        />
    )
}
