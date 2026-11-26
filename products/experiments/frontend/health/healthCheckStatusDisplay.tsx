import { IconCheck, IconMinus, IconQuestion } from '@posthog/icons'

import type { ListedHealthCheck } from './healthPanelChecks'

export const HEALTH_CHECK_STATUS_DISPLAY: Record<ListedHealthCheck['status'], { icon: JSX.Element; label: string }> = {
    not_checked: { icon: <IconQuestion className="text-secondary" />, label: "Couldn't check" },
    passed: { icon: <IconCheck className="text-success" />, label: 'No issue found' },
    not_applicable: { icon: <IconMinus className="text-tertiary" />, label: "Doesn't apply" },
}

export function healthCheckStatusText(check: ListedHealthCheck): string {
    const { label } = HEALTH_CHECK_STATUS_DISPLAY[check.status]
    if (!check.reason) {
        return label
    }
    // A reason for a check that couldn't run already starts with "Couldn't check" or "Couldn't read".
    return check.status === 'not_checked' ? check.reason : `${label} · ${check.reason}`
}
