import { useActions, useValues } from 'kea'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { StickinessComputationModes } from '~/queries/schema/schema-general'
import { EditorFilterProps } from '~/types'

export function QuillCumulativeStickinessFilter({ insightProps }: EditorFilterProps): JSX.Element {
    const { stickinessFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    return (
        <QuillSelect
            data-attr="stickiness-mode-select"
            value={stickinessFilter?.computedAs || StickinessComputationModes.NonCumulative}
            onChange={(value) => updateInsightFilter({ computedAs: value })}
            options={[
                {
                    label: 'Non-cumulative',
                    value: StickinessComputationModes.NonCumulative,
                    description: 'Show exact number of users active for each number of days',
                },
                {
                    label: 'Cumulative',
                    value: StickinessComputationModes.Cumulative,
                    description: 'Show number of users active for at least N days',
                },
            ]}
        />
    )
}
