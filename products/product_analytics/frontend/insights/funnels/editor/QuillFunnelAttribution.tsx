import { useActions, useValues } from 'kea'

import { QuillSelect, QuillSelectGroup } from 'lib/components/QuillSelect/QuillSelect'

import { FunnelsFilter } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, EditorFilterProps, StepOrderValue } from '~/types'

import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'

import { FUNNEL_STEP_COUNT_LIMIT } from './FunnelsQuerySteps'

export function QuillFunnelAttribution({ insightProps }: EditorFilterProps): JSX.Element {
    const { insightFilter, steps } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const { breakdownAttributionType, breakdownAttributionValue, funnelOrderType } = (insightFilter ||
        {}) as FunnelsFilter
    const isUnordered = funnelOrderType === StepOrderValue.UNORDERED

    const currentValue: string = !breakdownAttributionType
        ? BreakdownAttributionType.FirstTouch
        : breakdownAttributionType === BreakdownAttributionType.Step
          ? `${breakdownAttributionType}/${breakdownAttributionValue || 0}`
          : breakdownAttributionType

    const groups: QuillSelectGroup<string>[] = [
        {
            options: [
                { value: BreakdownAttributionType.FirstTouch, label: 'First touchpoint' },
                { value: BreakdownAttributionType.LastTouch, label: 'Last touchpoint' },
                { value: BreakdownAttributionType.AllSteps, label: 'All steps' },
                ...(isUnordered || currentValue === BreakdownAttributionType.Step
                    ? [{ value: BreakdownAttributionType.Step, label: 'Any step' }]
                    : []),
            ],
        },
    ]
    if (!isUnordered) {
        groups.push({
            label: 'Specific step',
            options: Array.from(Array(FUNNEL_STEP_COUNT_LIMIT).keys())
                .map((stepIndex) => ({
                    value: `${BreakdownAttributionType.Step}/${stepIndex}`,
                    label: `Step ${stepIndex + 1}`,
                }))
                .filter((option, stepIndex) => stepIndex < steps.length || option.value === currentValue),
        })
    }

    return (
        <QuillSelect
            value={currentValue}
            placeholder="Attribution"
            options={groups}
            onChange={(value) => {
                const [type, stepValue] = value.split('/')
                updateInsightFilter({
                    breakdownAttributionType: type as BreakdownAttributionType,
                    breakdownAttributionValue: stepValue ? parseInt(stepValue) : 0,
                })
            }}
            data-attr="breakdown-attributions"
        />
    )
}
