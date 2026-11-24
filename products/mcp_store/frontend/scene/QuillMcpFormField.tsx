import { Field as KeaField } from 'kea-forms'
import type { ReactElement, ReactNode } from 'react'

import { Field, FieldDescription, FieldError, FieldLabel } from '@posthog/quill'

export interface QuillMcpFormFieldControl {
    id: string
    value: any
    onChange: (value: any) => void
}

export function QuillMcpFormField({
    name,
    label,
    description,
    children,
}: {
    name: string
    label: string
    description?: ReactNode
    children: (control: QuillMcpFormFieldControl) => ReactElement
}): JSX.Element {
    return (
        <KeaField name={name} noStyle>
            {({ id, value, onChange, error }) => (
                <Field data-invalid={error ? true : undefined}>
                    <FieldLabel htmlFor={id}>{label}</FieldLabel>
                    {children({ id, value, onChange })}
                    {description && <FieldDescription>{description}</FieldDescription>}
                    {error && <FieldError>{error}</FieldError>}
                </Field>
            )}
        </KeaField>
    )
}
