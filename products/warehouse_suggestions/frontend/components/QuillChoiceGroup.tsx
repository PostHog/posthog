import { ReactNode } from 'react'

import {
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    FieldLegend,
    FieldSet,
    RadioGroup,
    RadioGroupItem,
} from '@posthog/quill'

export interface QuillChoice<T extends string> {
    value: T
    label: ReactNode
    description?: ReactNode
    disabledReason?: string
    'data-attr'?: string
}

export function QuillChoiceGroup<T extends string>({
    legend,
    idPrefix,
    value,
    onChange,
    choices,
    disabled,
}: {
    legend: string
    idPrefix: string
    value: T
    onChange: (value: T) => void
    choices: QuillChoice<T>[]
    disabled: boolean
}): JSX.Element {
    return (
        <FieldSet disabled={disabled}>
            <FieldLegend variant="label">{legend}</FieldLegend>
            <RadioGroup aria-label={legend} value={value} onValueChange={(choice) => onChange(choice as T)}>
                {choices.map((choice) => (
                    <Field
                        key={choice.value}
                        orientation="horizontal"
                        className="items-start"
                        data-disabled={!!choice.disabledReason}
                    >
                        <RadioGroupItem
                            value={choice.value}
                            id={`${idPrefix}-${choice.value}`}
                            disabled={!!choice.disabledReason}
                            className="data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50"
                            data-attr={choice['data-attr']}
                        />
                        <FieldContent>
                            <FieldLabel htmlFor={`${idPrefix}-${choice.value}`}>{choice.label}</FieldLabel>
                            <FieldDescription>{choice.description}</FieldDescription>
                            {choice.disabledReason && <FieldDescription>{choice.disabledReason}</FieldDescription>}
                        </FieldContent>
                    </Field>
                ))}
            </RadioGroup>
        </FieldSet>
    )
}
