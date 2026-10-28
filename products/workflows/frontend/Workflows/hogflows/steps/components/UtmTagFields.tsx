import { LemonInput } from '@posthog/lemon-ui'

export type UtmTagKey = 'utm_source' | 'utm_medium' | 'utm_campaign' | 'utm_content'
export type UtmTagValues = Partial<Record<UtmTagKey, string>>

export const UTM_TAG_KEYS: UtmTagKey[] = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content']

export interface UtmTagFieldsProps {
    value: UtmTagValues
    onChange: (value: UtmTagValues) => void
    /** What utm_campaign and utm_content get when left empty. */
    campaignDefault: string
    contentDefault: string
}

export function UtmTagFields({ value, onChange, campaignDefault, contentDefault }: UtmTagFieldsProps): JSX.Element {
    const defaults: Record<UtmTagKey, string> = {
        utm_source: 'posthog',
        utm_medium: 'email',
        utm_campaign: campaignDefault,
        utm_content: contentDefault,
    }
    const values = UTM_TAG_KEYS.map((key) => [key, (value[key] || defaults[key]).trim()] as const).filter(
        ([, tagValue]) => tagValue
    )
    // Encoded like the sent links, except variables, which stay readable because they differ per person.
    const example = values
        .map(([key, tagValue]) => `${key}=${tagValue.includes('{{') ? tagValue : encodeURIComponent(tagValue)}`)
        .join('&')
    const hasVariables = values.some(([, tagValue]) => tagValue.includes('{{'))

    return (
        <div className="flex flex-col gap-1">
            <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 items-center">
                {UTM_TAG_KEYS.map((key) => (
                    <div key={key} className="contents">
                        <span className="text-xs font-mono text-secondary">{key}</span>
                        <LemonInput
                            size="small"
                            value={value[key] ?? ''}
                            placeholder={defaults[key] || 'Not set'}
                            onChange={(next) => {
                                const { [key]: _, ...rest } = value
                                onChange(next.trim() ? { ...rest, [key]: next } : rest)
                            }}
                            data-attr={`email-utm-${key.replace('utm_', '')}`}
                        />
                    </div>
                ))}
            </div>
            <span className="text-xs text-secondary">
                Leave a field empty to use the value shown. Fields accept variables like{' '}
                <code>{'{{ person.properties.plan }}'}</code>.
            </span>
            <span className="text-xs text-secondary break-all">
                Example: https://example.com/?{example}
                {hasVariables ? ' (variables are filled in for each person)' : ''}
            </span>
        </div>
    )
}
