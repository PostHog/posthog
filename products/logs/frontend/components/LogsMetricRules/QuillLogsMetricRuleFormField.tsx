import { Field as KeaField } from 'kea-forms'
import type { ReactElement, ReactNode } from 'react'

import { Field, FieldDescription, FieldError, FieldLabel } from '@posthog/quill'

import type { LogsMetricRuleFormType } from './logsMetricRuleFormLogic'

export interface QuillLogsMetricRuleFormFieldControl {
    id: string
    value: any
    onChange: (value: any) => void
    invalid: boolean
}

export interface QuillLogsMetricRuleFormFieldProps {
    name: keyof LogsMetricRuleFormType
    label: string
    description?: ReactNode
    children: (control: QuillLogsMetricRuleFormFieldControl) => ReactElement
}

export function QuillLogsMetricRuleFormField({
    name,
    label,
    description,
    children,
}: QuillLogsMetricRuleFormFieldProps): JSX.Element {
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
