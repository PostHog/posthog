import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'

import { funnelDataLogic } from '../funnelDataLogic'

export function FunnelStepBarLabelsPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    return (
        <LemonSegmentedButton
            className="pb-2 px-2"
            value={funnelsFilter?.stepBarLabels ?? 'percentage'}
            onChange={(stepBarLabels) => {
                updateInsightFilter({ stepBarLabels })
                posthog.capture('funnel bar labels changed', { labels: stepBarLabels })
            }}
            options={[
                { value: 'percentage', label: 'Percentage', 'data-attr': 'funnel-bar-labels-percentage' },
                { value: 'count', label: 'Count', 'data-attr': 'funnel-bar-labels-count' },
                { value: 'both', label: 'Both', 'data-attr': 'funnel-bar-labels-both' },
            ]}
            size="small"
            fullWidth
        />
    )
}
