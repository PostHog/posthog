import { useActions, useValues } from 'kea'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { FunnelStepReference } from '~/types'

import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'

export function QuillFunnelStepReferencePicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnelStepReference } = (insightFilter || {}) as FunnelsFilter

    return (
        <QuillSelect
            value={funnelStepReference || FunnelStepReference.total}
            onChange={(stepRef) => updateInsightFilter({ funnelStepReference: stepRef })}
            data-attr="funnel-step-reference-selector"
            options={[
                { value: FunnelStepReference.total, label: 'Overall conversion' },
                { value: FunnelStepReference.previous, label: 'Relative to previous step' },
            ]}
        />
    )
}
