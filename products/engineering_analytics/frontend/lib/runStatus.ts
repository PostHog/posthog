import { LemonTagType } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'

import { isDecisiveFailure, isPassingConclusion } from './lifecycle'

export function verdictTag(conclusion: string | null): { label: string; type: LemonTagType } {
    if (conclusion === null) {
        return { label: 'Running', type: 'warning' }
    }
    const label = capitalizeFirstLetter(conclusion.replace('_', ' '))
    if (isDecisiveFailure(conclusion)) {
        return { label, type: 'danger' }
    }
    if (isPassingConclusion(conclusion)) {
        return { label, type: conclusion === 'success' ? 'success' : 'muted' }
    }
    // Cancelled is neither a pass nor a decisive failure, so it is neutral, not amber.
    if (conclusion === 'cancelled') {
        return { label, type: 'muted' }
    }
    return { label, type: 'warning' }
}

// Keyed by the `verdictTag` type, so every run-activity chart and the run tables' StatusDot give one
// conclusion one color.
export const VERDICT_COLOR: Record<string, string> = {
    success: 'var(--success)',
    danger: 'var(--danger)',
    warning: 'var(--warning)',
    muted: 'var(--muted)',
}
