import { LemonTagType } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils/strings'

import { isPassingConclusion } from './lifecycle'

/**
 * A workflow run's conclusion as a labeled tag. `null` conclusion means the run is still in progress.
 * Decisive failures (failure / timed_out) are danger; success is green; other passing outcomes
 * (skipped / neutral / cancelled) are muted; anything else (e.g. action_required) is a warning.
 */
export function verdictTag(conclusion: string | null): { label: string; type: LemonTagType } {
    if (conclusion === null) {
        return { label: 'Running', type: 'warning' }
    }
    const label = capitalizeFirstLetter(conclusion.replace('_', ' '))
    if (conclusion === 'failure' || conclusion === 'timed_out') {
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
