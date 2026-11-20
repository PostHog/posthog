import { Field as KeaField } from 'kea-forms'

import { Field, FieldDescription, FieldError, FieldLabel, Input } from '@posthog/quill'

export function QuillHarnessFormField({
    name,
    label,
    description,
    placeholder,
    maxLength,
    autoFocus,
    className,
}: {
    name: string
    label: string
    description?: string
    placeholder: string
    maxLength?: number
    autoFocus?: boolean
    className?: string
}): JSX.Element {
    return (
        <KeaField name={name} noStyle>
            {({ id, value, onChange, error }) => (
                <Field data-invalid={error ? true : undefined} className={className}>
                    <FieldLabel htmlFor={id}>{label}</FieldLabel>
                    <Input
                        id={id}
                        value={value ?? ''}
                        onChange={(event) => onChange(event.target.value)}
                        placeholder={placeholder}
                        maxLength={maxLength}
                        autoFocus={autoFocus}
                        aria-invalid={error ? true : undefined}
                    />
                    {description && <FieldDescription>{description}</FieldDescription>}
                    {error && <FieldError>{error}</FieldError>}
                </Field>
            )}
        </KeaField>
    )
}
