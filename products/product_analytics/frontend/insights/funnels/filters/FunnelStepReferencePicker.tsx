import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { QuillChartOptionSelect } from 'lib/components/ChartOptions/QuillChartOptionSelect'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightLogic } from 'scenes/insights/insightLogic'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { FunnelStepReference } from '~/types'

import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'

export function FunnelStepReferencePicker(): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { insightFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const { funnelStepReference } = (insightFilter || {}) as FunnelsFilter

    const options = [
        {
            value: FunnelStepReference.total,
            label: 'Overall conversion',
        },
        {
            value: FunnelStepReference.previous,
            label: 'Relative to previous step',
        },
    ]
    const value = funnelStepReference || FunnelStepReference.total
    const onChange = (stepRef: FunnelStepReference | null): void => {
        if (stepRef) {
            updateInsightFilter({ funnelStepReference: stepRef })
        }
    }

    if (quillSurface) {
        return (
            <QuillChartOptionSelect
                data-attr="funnel-step-reference-selector"
                value={value}
                onChange={onChange}
                options={options}
            />
        )
    }

    return (
        <LemonSelect
            value={value}
            onChange={onChange}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-step-reference-selector"
            options={options}
        />
    )
}
