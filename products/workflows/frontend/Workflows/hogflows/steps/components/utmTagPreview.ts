import type { UtmTagKey, UtmTagValues } from './UtmTagFields'

export interface UtmTagPreview {
    /** What each tag gets when its field is left empty. */
    defaults: Record<UtmTagKey, string>
    example: string
    hasVariables: boolean
}

export function getUtmTagPreview(value: UtmTagValues, campaignDefault: string, contentDefault: string): UtmTagPreview {
    const defaults: Record<UtmTagKey, string> = {
        utm_source: 'posthog',
        utm_medium: 'email',
        utm_campaign: campaignDefault,
        utm_content: contentDefault,
    }
    const values = (Object.keys(defaults) as UtmTagKey[])
        .map((key) => [key, (value[key] || defaults[key]).trim()] as const)
        .filter(([, tagValue]) => tagValue)
    // Encoded like the sent links, except variables, which stay readable because they differ per person.
    const example = values
        .map(([key, tagValue]) => `${key}=${tagValue.includes('{{') ? tagValue : encodeURIComponent(tagValue)}`)
        .join('&')
    const hasVariables = values.some(([, tagValue]) => tagValue.includes('{{'))

    return { defaults, example, hasVariables }
}

/** An empty field drops its key, so the tag falls back to its default. */
export function setUtmTagValue(value: UtmTagValues, key: UtmTagKey, next: string): UtmTagValues {
    const { [key]: _, ...rest } = value
    return next.trim() ? { ...rest, [key]: next } : rest
}
