import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function RetentionReferencePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { retentionFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const { retentionReference } = retentionFilter || {}

    return (
        <LemonSelect
            className="w-60"
            size="small"
            value={retentionReference || 'total'}
            onChange={(retentionReference) => {
                updateInsightFilter({ retentionReference })
            }}
            options={[
                {
                    value: 'total',
                    label: 'starting cohort size',
                    tooltip:
                        'eg. Retention for day 3 will be percentage of users who returned on day 3 as a percentage of users on day 0 (users who preformed start event)',
                },
                {
                    value: 'previous',
                    label: 'previous period',
                    tooltip:
                        'eg. Retention for day 3 will be percentage of users who returned on day 3 as a percentage of users who returned on day 2 (the previous period)',
                },
            ]}
        />
    )
}
