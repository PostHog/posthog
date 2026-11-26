export interface FeatureFlagRequestListField {
    id: string
    label: string
    help: string
    noun: string
    placeholder: string
    dataAttr: string
    value: string[]
    onChange: (entries: string[]) => void
}

export const HOST_LIST_FIELD = { noun: 'domain', placeholder: 'example.com' }
export const IP_LIST_FIELD = { noun: 'IP address', placeholder: '203.0.113.7 or 198.51.100.0/24' }
