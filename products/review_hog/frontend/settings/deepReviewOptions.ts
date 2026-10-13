import type { UrgencyThresholdEnumApi } from 'products/review_hog/frontend/generated/api.schemas'

export const THRESHOLD_OPTIONS: { value: UrgencyThresholdEnumApi; label: string }[] = [
    { value: 'consider', label: 'All findings' },
    { value: 'should_fix', label: 'Should fix and above' },
    { value: 'must_fix', label: 'Must fix only' },
]

export type OnOff = 'on' | 'off'

export function toOnOff(value: boolean): OnOff {
    return value ? 'on' : 'off'
}

export const ON_OFF_OPTIONS: { value: OnOff; label: string }[] = [
    { value: 'on', label: 'On' },
    { value: 'off', label: 'Off' },
]
