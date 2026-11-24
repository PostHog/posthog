import { ChangeEvent } from 'react'

import { Field, FieldLabel, Textarea } from '@posthog/quill'

import { DISMISS_NOTE_LABEL, DISMISS_NOTE_MAX_LENGTH, DISMISS_NOTE_PLACEHOLDER } from '../dismissReasons'

export interface QuillDismissNoteFieldProps {
    id: string
    value: string
    onChange: (note: string) => void
    dataAttr: string
}

export function QuillDismissNoteField({ id, value, onChange, dataAttr }: QuillDismissNoteFieldProps): JSX.Element {
    return (
        <Field>
            <FieldLabel htmlFor={id}>{DISMISS_NOTE_LABEL}</FieldLabel>
            <Textarea
                id={id}
                rows={3}
                value={value}
                maxLength={DISMISS_NOTE_MAX_LENGTH}
                placeholder={DISMISS_NOTE_PLACEHOLDER}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)}
                data-attr={dataAttr}
            />
        </Field>
    )
}
