import { useId } from 'react'

import { Field, FieldContent, FieldDescription, FieldLabel, RadioGroup, RadioGroupItem } from '@posthog/quill'

import { ExperimentStatsMethod } from '~/types'

import { STATS_METHOD_OPTIONS } from './statsMethodOptions'

export function QuillStatsMethodSelector({
    value,
    onChange,
    disabledReason,
}: {
    value: ExperimentStatsMethod
    onChange: (method: ExperimentStatsMethod) => void
    disabledReason?: string | null
}): JSX.Element {
    const idPrefix = useId()

    return (
        <RadioGroup
            value={value}
            onValueChange={(next) => onChange(next as ExperimentStatsMethod)}
            className="max-w-160"
        >
            {STATS_METHOD_OPTIONS.map((option) => {
                const optionId = `${idPrefix}-${option.value}`

                return (
                    <Field key={option.value} orientation="horizontal" className="items-start">
                        <RadioGroupItem id={optionId} value={option.value} disabledReason={disabledReason} />
                        <FieldContent>
                            <FieldLabel htmlFor={optionId}>{option.title}</FieldLabel>
                            <FieldDescription>{option.description}</FieldDescription>
                        </FieldContent>
                    </Field>
                )
            })}
        </RadioGroup>
    )
}
