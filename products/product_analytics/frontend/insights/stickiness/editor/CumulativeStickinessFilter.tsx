import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { StickinessComputationModes } from '~/queries/schema/schema-general'
import { EditorFilterProps } from '~/types'

export function CumulativeStickinessFilter({ insightProps }: EditorFilterProps): JSX.Element {
    const { stickinessFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <LemonSelect
            className="w-48"
            data-attr="stickiness-mode-select"
            value={stickinessFilter?.computedAs || StickinessComputationModes.NonCumulative}
            onChange={(value) => {
                updateInsightFilter({
                    computedAs: value,
                })
            }}
            options={[
                {
                    label: 'Non-cumulative',
                    value: StickinessComputationModes.NonCumulative,
                    tooltip: 'Show exact number of users active for each number of days',
                },
                {
                    label: 'Cumulative',
                    value: StickinessComputationModes.Cumulative,
                    tooltip: 'Show number of users active for at least N days',
                },
            ]}
        />
    )
}
