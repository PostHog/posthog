import { useActions, useValues } from 'kea'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function QuillRetentionReferencePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <QuillSelect<'total' | 'previous'>
            value={retentionFilter?.retentionReference || 'total'}
            onChange={(retentionReference) => updateInsightFilter({ retentionReference })}
            options={[
                {
                    value: 'total',
                    label: 'starting cohort size',
                    description:
                        'eg. Retention for day 3 will be percentage of users who returned on day 3 as a percentage of users on day 0 (users who preformed start event)',
                },
                {
                    value: 'previous',
                    label: 'previous period',
                    description:
                        'eg. Retention for day 3 will be percentage of users who returned on day 3 as a percentage of users who returned on day 2 (the previous period)',
                },
            ]}
        />
    )
}
