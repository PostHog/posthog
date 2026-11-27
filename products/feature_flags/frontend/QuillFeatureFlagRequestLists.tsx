import { useId } from 'react'

import { Field, FieldDescription, FieldLabel } from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'

import type { FeatureFlagRequestListField } from './featureFlagRequestListField'
import { splitRequestListEntries } from './splitRequestListEntries'

export function QuillFeatureFlagRequestLists({
    lists,
    disabled,
    disabledReason,
}: {
    lists: FeatureFlagRequestListField[]
    disabled: boolean
    disabledReason?: string | null
}): JSX.Element {
    const baseId = useId()

    return (
        <div className="flex max-w-160 flex-col gap-4">
            {lists.map(({ id, label, help, noun, placeholder, dataAttr, value, onChange }) => (
                <Field key={id}>
                    <FieldLabel htmlFor={`${baseId}-${id}`}>{label}</FieldLabel>
                    <TagsCombobox
                        id={`${baseId}-${id}`}
                        value={value}
                        onChange={(entries) => onChange(splitRequestListEntries(entries))}
                        customValueNoun={noun}
                        dataAttr={dataAttr}
                        placeholder={placeholder}
                        disabled={disabled}
                        disabledReason={disabledReason}
                        className="w-full"
                    />
                    <FieldDescription>{help}</FieldDescription>
                </Field>
            ))}
        </div>
    )
}
