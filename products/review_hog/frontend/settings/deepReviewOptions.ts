import type {
    ReviewProjectSettingsApi,
    ReviewUserSettingsApi,
    UrgencyThresholdEnumApi,
} from 'products/review_hog/frontend/generated/api.schemas'

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

/** The project settings answer first after an admin edit; the personal settings reload after it. */
export function projectDeepDefaults(
    projectSettings: ReviewProjectSettingsApi | null,
    settings: ReviewUserSettingsApi | null
): { threshold: UrgencyThresholdEnumApi; celebrate: OnOff } {
    const loaded = settings?.project_defaults
    return {
        threshold: projectSettings?.urgency_threshold ?? loaded?.urgency_threshold ?? 'consider',
        celebrate: toOnOff(projectSettings?.celebrate_clean_reviews ?? loaded?.celebrate_clean_reviews ?? true),
    }
}
