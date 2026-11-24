import { useId } from 'react'

import { Input, Label, Text } from '@posthog/quill'

import { UTM_TAG_KEYS, UtmTagFieldsProps } from './UtmTagFields'
import { getUtmTagPreview, setUtmTagValue } from './utmTagPreview'

export function QuillUtmTagFields({
    value,
    onChange,
    campaignDefault,
    contentDefault,
}: UtmTagFieldsProps): JSX.Element {
    const idPrefix = useId()
    const { defaults, example, hasVariables } = getUtmTagPreview(value, campaignDefault, contentDefault)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-1">
                {UTM_TAG_KEYS.map((key) => {
                    const inputId = `${idPrefix}-${key}`

                    return (
                        <div key={key} className="flex items-center gap-2">
                            <Label htmlFor={inputId} className="w-24 shrink-0 font-mono text-muted-foreground">
                                {key}
                            </Label>
                            <Input
                                id={inputId}
                                size="sm"
                                value={value[key] ?? ''}
                                placeholder={defaults[key] || 'Not set'}
                                onChange={(event) => onChange(setUtmTagValue(value, key, event.target.value))}
                                data-attr={`email-utm-${key.replace('utm_', '')}`}
                                className="min-w-0 flex-1"
                            />
                        </div>
                    )
                })}
            </div>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                Leave a field empty to use the value shown. Fields accept variables like{' '}
                <code>{'{{ person.properties.plan }}'}</code>.
            </Text>
            <Text size="xs" variant="muted" render={<p className="m-0 break-all" />}>
                <span>Example: https://example.com/?</span>
                <span translate="no">{example}</span>
                {hasVariables && <span> (variables are filled in for each person)</span>}
            </Text>
        </div>
    )
}
