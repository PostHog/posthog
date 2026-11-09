import { useActions, useValues } from 'kea'

import { IconClock, IconFilter, IconTrending } from '@posthog/icons'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { EditorFilterProps, FunnelVizType as VizType } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'

export interface FunnelVizTypeOption {
    value: VizType
    title: string
    description: string
    icon: JSX.Element
}

export function useFunnelVizType({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): {
    value: VizType
    options: FunnelVizTypeOption[]
    setValue: (value: VizType) => void
} {
    const { aggregationTargetLabel, insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const { funnelVizType } = (insightFilter || {}) as FunnelsFilter

    return {
        value: funnelVizType || VizType.Steps,
        options: [
            {
                value: VizType.Steps,
                title: 'Conversion steps',
                description: `Track ${aggregationTargetLabel.plural} progress between steps of the funnel`,
                icon: <IconFilter className="text-secondary" />,
            },
            {
                value: VizType.TimeToConvert,
                title: 'Time to convert',
                description: `Track how long it takes for ${aggregationTargetLabel.plural} to convert`,
                icon: <IconClock className="text-secondary" />,
            },
            {
                value: VizType.Trends,
                title: 'Historical trends',
                description: "Track how this funnel's conversion rate is trending over time",
                icon: <IconTrending className="text-secondary" />,
            },
        ],
        setValue: (value) => {
            if (funnelVizType !== value) {
                updateInsightFilter({ funnelVizType: value })
            }
        },
    }
}
