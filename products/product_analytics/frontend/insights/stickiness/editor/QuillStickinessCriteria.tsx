import { useActions, useValues } from 'kea'

import { Input } from '@posthog/quill'

import { OperatorSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { StickinessOperator } from '~/queries/schema/schema-general'
import { EditorFilterProps, PropertyOperator } from '~/types'

const OPERATORS: StickinessOperator[] = [
    PropertyOperator.LessThanOrEqual,
    PropertyOperator.GreaterThanOrEqual,
    PropertyOperator.Exact,
]

export function QuillStickinessCriteria({ insightProps }: EditorFilterProps): JSX.Element {
    const { stickinessFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const currentOperator = stickinessFilter?.stickinessCriteria?.operator ?? PropertyOperator.GreaterThanOrEqual
    const currentValue = stickinessFilter?.stickinessCriteria?.value ?? 1

    return (
        <div className="flex items-center gap-2 @min-[0px]/editor-panel:flex-wrap">
            <div className="flex-1 @min-[0px]/editor-panel:flex-none @min-[0px]/editor-panel:min-w-0">
                <OperatorSelect
                    operator={currentOperator}
                    operators={OPERATORS}
                    onChange={(newOperator: PropertyOperator) => {
                        updateInsightFilter({
                            stickinessCriteria: { operator: newOperator as StickinessOperator, value: currentValue },
                        })
                    }}
                />
            </div>
            <Input
                type="number"
                className="w-20"
                aria-label="Times per interval"
                defaultValue={currentValue}
                min={1}
                onChange={(e) => {
                    const newValue = Number(e.target.value)
                    // A cleared or half-typed field is not a valid integer, and the backend needs at least 1
                    if (e.target.value === '' || !Number.isFinite(newValue)) {
                        return
                    }
                    updateInsightFilter({
                        stickinessCriteria: { operator: currentOperator, value: Math.max(1, Math.floor(newValue)) },
                    })
                }}
            />
            <span className="@min-[0px]/editor-panel:whitespace-nowrap">time(s) per interval</span>
        </div>
    )
}
