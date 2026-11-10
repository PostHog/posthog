import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { QuillChartOptionSelect } from 'lib/components/ChartOptions/QuillChartOptionSelect'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { StepOrderValue } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'

interface StepOption {
    key?: string
    label: string
    value: StepOrderValue
}

const options: StepOption[] = [
    {
        label: 'Sequential',
        value: StepOrderValue.ORDERED,
    },
    {
        label: 'Strict order',
        value: StepOrderValue.STRICT,
    },
    {
        label: 'Any order',
        value: StepOrderValue.UNORDERED,
    },
]

export function FunnelStepOrderPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const { funnelOrderType } = (insightFilter || {}) as FunnelsFilter
    const value = funnelOrderType || StepOrderValue.ORDERED
    const onChange = (stepOrder: StepOrderValue | null): void => {
        if (stepOrder) {
            updateInsightFilter({ funnelOrderType: stepOrder })
        }
    }

    if (quillSurface) {
        return (
            <QuillChartOptionSelect
                data-attr="funnel-step-order-filter"
                value={value}
                onChange={onChange}
                options={options}
            />
        )
    }

    return (
        <LemonSelect
            id="funnel-step-order-filter"
            data-attr="funnel-step-order-filter"
            value={value}
            onChange={onChange}
            dropdownMatchSelectWidth={false}
            options={options}
        />
    )
}
