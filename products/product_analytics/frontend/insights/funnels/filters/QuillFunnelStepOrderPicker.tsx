import { useActions, useValues } from 'kea'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { StepOrderValue } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'

export function QuillFunnelStepOrderPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { funnelOrderType } = (insightFilter || {}) as FunnelsFilter

    return (
        <QuillSelect
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            value={funnelOrderType || StepOrderValue.ORDERED}
            onChange={(stepOrder) => updateInsightFilter({ funnelOrderType: stepOrder })}
            options={[
                { label: 'Sequential', value: StepOrderValue.ORDERED },
                { label: 'Strict order', value: StepOrderValue.STRICT },
                { label: 'Any order', value: StepOrderValue.UNORDERED },
            ]}
        />
    )
}
