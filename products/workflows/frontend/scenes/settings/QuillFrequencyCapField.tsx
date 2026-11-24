import {
    Field,
    FieldDescription,
    FieldError,
    FieldLabel,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldRoot,
} from '@posthog/quill'

import { toFrequencyCapInputValue } from './frequencyCap'

export interface QuillFrequencyCapFieldProps {
    id: string
    label: string
    value: number | null
    onChange: (value: number | null) => void
    max: number
    placeholder: string
    error?: string
    descriptions?: string[]
    disabledReason?: string | null
    dataAttr: string
}

export function QuillFrequencyCapField({
    id,
    label,
    value,
    onChange,
    max,
    placeholder,
    error,
    descriptions,
    disabledReason,
    dataAttr,
}: QuillFrequencyCapFieldProps): JSX.Element {
    return (
        <Field data-invalid={error ? true : undefined} className="min-w-60 flex-1">
            <FieldLabel htmlFor={id}>{label}</FieldLabel>
            <NumberFieldRoot
                value={value}
                onValueChange={(next: number | null) => onChange(toFrequencyCapInputValue(next))}
                min={1}
                max={max}
                allowOutOfRange
                disabledReason={disabledReason}
            >
                <NumberFieldGroup>
                    <NumberFieldInput
                        id={id}
                        placeholder={placeholder}
                        aria-invalid={error ? true : undefined}
                        data-attr={dataAttr}
                    />
                </NumberFieldGroup>
            </NumberFieldRoot>
            {descriptions?.map((description) => (
                <FieldDescription key={description}>{description}</FieldDescription>
            ))}
            {error && <FieldError>{error}</FieldError>}
        </Field>
    )
}
