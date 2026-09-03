import { LemonTagType } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'

import { isDecisiveFailure, isPassingConclusion } from './lifecycle'

/**
 * A workflow run's conclusion as a labeled tag. `null` = still in progress. Decisive failures
 * are danger; success green; other passing outcomes muted; else warning.
 */
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
    // Cancelled is neither a pass nor a decisive failure — neutral, not amber.
    if (conclusion === 'cancelled') {
        return { label, type: 'muted' }
    }
    return { label, type: 'warning' }
}

// CSS color per verdict type, keyed by the `verdictTag` type above so every run-activity chart (scatter,
// mini bars) and the run tables' StatusDot color the same conclusion identically.
export const VERDICT_COLOR: Record<string, string> = {
    success: 'var(--success)',
    danger: 'var(--danger)',
    warning: 'var(--warning)',
    muted: 'var(--muted)',
}
