import { useId } from 'react'

import { Field, FieldLabel, ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { FilterLogicalOperator } from '~/types'

export interface MatchModeToggleProps {
    /** Read by screen readers only. The two options say the rest. */
    label: string
    value: FilterLogicalOperator
    onChange: (matchMode: FilterLogicalOperator) => void
    allLabel: string
    anyLabel: string
    allDataAttr: string
    anyDataAttr: string
}

export function MatchModeToggle({
    label,
    value,
    onChange,
    allLabel,
    anyLabel,
    allDataAttr,
    anyDataAttr,
}: MatchModeToggleProps): JSX.Element {
    const labelId = useId()

    return (
        <Field className="w-auto">
            <FieldLabel id={labelId} className="sr-only">
                {label}
            </FieldLabel>
            <ToggleGroup
                aria-labelledby={labelId}
                variant="outline"
                size="sm"
                value={[value]}
                onValueChange={([nextMatchMode]) => {
                    // A press on the active option clears the selection, and one of the two must stay chosen.
                    if (nextMatchMode === FilterLogicalOperator.And || nextMatchMode === FilterLogicalOperator.Or) {
                        onChange(nextMatchMode)
                    }
                }}
            >
                <ToggleGroupItem value={FilterLogicalOperator.And} data-attr={allDataAttr}>
                    {allLabel}
                </ToggleGroupItem>
                <ToggleGroupItem value={FilterLogicalOperator.Or} data-attr={anyDataAttr}>
                    {anyLabel}
                </ToggleGroupItem>
            </ToggleGroup>
        </Field>
    )
}
