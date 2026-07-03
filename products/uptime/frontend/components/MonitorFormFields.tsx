import { Field as KeaField } from 'kea-forms'

import { Field, FieldError, FieldGroup, FieldLabel, Input } from '@posthog/quill-primitives'

interface MonitorTextFieldProps {
    name: 'name' | 'url'
    label: string
    placeholder: string
    autoFocus?: boolean
}

function MonitorTextField({ name, label, placeholder, autoFocus }: MonitorTextFieldProps): JSX.Element {
    return (
        <KeaField name={name} noStyle>
            {({ value, onChangeEvent, id, error }) => (
                <Field>
                    <FieldLabel htmlFor={id}>{label}</FieldLabel>
                    <Input
                        id={id}
                        value={value ?? ''}
                        onChange={onChangeEvent}
                        placeholder={placeholder}
                        autoFocus={autoFocus}
                        aria-invalid={error ? true : undefined}
                        autoComplete="off"
                        data-1p-ignore
                    />
                    {error ? <FieldError>{error}</FieldError> : null}
                </Field>
            )}
        </KeaField>
    )
}

/** Name + URL fields shared by the create and edit monitor dialogs. Must render inside a kea `Form`. */
export function MonitorFormFields(): JSX.Element {
    return (
        <FieldGroup>
            <MonitorTextField name="name" label="Name" placeholder="My website" autoFocus />
            <MonitorTextField name="url" label="URL" placeholder="https://example.com" />
        </FieldGroup>
    )
}
