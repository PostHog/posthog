import type { LogsSamplingFormType } from './logsSamplingFormLogic'

/**
 * Returns the reason the Save button should be disabled, or null when save is allowed.
 *
 * kea-forms can't express scalar errors on object-shaped fields (the filter group),
 * so the "filter group must be non-empty" check is surfaced via this pure function
 * and consumed directly by the scene's submit button.
 */
export function samplingFormSaveDisabledReason(form: LogsSamplingFormType): string | null {
    if (form.filter_group.values.length === 0) {
        return 'Add at least one filter to match logs'
    }
    return null
}
