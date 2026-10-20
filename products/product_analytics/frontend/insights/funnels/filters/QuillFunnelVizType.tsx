import { useActions, useValues } from 'kea'

import { IconClock, IconFilter, IconTrending } from '@posthog/icons'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { EditorFilterProps, FunnelVizType as VizType } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'

export function QuillFunnelVizType({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element | null {
    const { aggregationTargetLabel, insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnelVizType } = (insightFilter || {}) as FunnelsFilter

    if (funnelVizType === VizType.Flow) {
        return null
    }

    return (
        <QuillSelect
            value={funnelVizType || VizType.Steps}
            onChange={(value) => {
                if (funnelVizType !== value) {
                    updateInsightFilter({ funnelVizType: value })
                }
            }}
            options={[
                {
                    value: VizType.Steps,
                    icon: <IconFilter />,
                    label: 'Conversion steps',
                    description: `Track ${aggregationTargetLabel.plural} progress between steps of the funnel`,
                },
                {
                    value: VizType.TimeToConvert,
                    icon: <IconClock />,
                    label: 'Time to convert',
                    description: `Track how long it takes for ${aggregationTargetLabel.plural} to convert`,
                },
                {
                    value: VizType.Trends,
                    icon: <IconTrending />,
                    label: 'Historical trends',
                    description: "Track how this funnel's conversion rate is trending over time",
                },
            ]}
            data-attr="funnel-viz-type-select"
        />
    )
}
