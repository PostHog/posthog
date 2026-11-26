import { Field as KeaField } from 'kea-forms'
import { ReactElement, ReactNode } from 'react'

import { Field, FieldDescription, FieldError, FieldLabel } from '@posthog/quill'

export interface QuillConfigurationFormFieldControl {
    id: string
    value: any
    onChange: (value: any) => void
    invalid: boolean
}

export function QuillConfigurationFormField({
    name,
    label,
    description,
    children,
}: {
    name: string
    label: ReactNode
    description?: ReactNode
    children: (control: QuillConfigurationFormFieldControl) => ReactElement
}): JSX.Element {
    return (
        <KeaField name={name} noStyle>
            {({ id, value, onChange, error }) => (
                <Field data-invalid={error ? true : undefined}>
                    <FieldLabel htmlFor={id}>{label}</FieldLabel>
                    {children({ id, value, onChange, invalid: !!error })}
                    {description && <FieldDescription>{description}</FieldDescription>}
                    {error && <FieldError>{error}</FieldError>}
                </Field>
            )}
        </KeaField>
    )
}
