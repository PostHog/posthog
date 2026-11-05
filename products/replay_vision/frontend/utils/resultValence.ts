import { IconCheckCircle, IconQuestion, IconXCircle } from '@posthog/icons'

import type { PromptValenceEnumApi, ReplayObservationApi } from '../generated/api.schemas'
import { configFromSnapshot, type ScorerScannerConfig } from '../replay_scanners/types'
import type { ConfidenceLevel, MonitorVerdict } from './observation'

// The `--success`/`--danger` family LemonTag uses. The `text-success` utility maps to a different, brighter green.
const GOOD_CLASS = 'text-success-dark dark:text-success-light'
const BAD_CLASS = 'text-danger-dark dark:text-danger-light'

/** Text color for each confidence level, from the same color family as the verdicts. */
export const CONFIDENCE_CLASS: Record<ConfidenceLevel['type'], string> = {
    success: GOOD_CLASS,
    warning: 'text-warning-dark dark:text-warning',
    danger: BAD_CLASS,
}

export const VERDICT_ICON: Record<MonitorVerdict, typeof IconCheckCircle> = {
    yes: IconCheckCircle,
    no: IconXCircle,
    inconclusive: IconQuestion,
}

type Direction = 'good' | 'bad'

function direction(valence: PromptValenceEnumApi | null): Direction | null {
    return valence === 'good' || valence === 'bad' ? valence : null
}

function verdictClass(verdict: MonitorVerdict, yesIs: Direction | null): string {
    if (verdict === 'inconclusive') {
        return 'text-secondary dark:text-default'
    }
    if (!yesIs) {
        return 'text-default'
    }
    return (verdict === 'yes') === (yesIs === 'good') ? GOOD_CLASS : BAD_CLASS
}

export function scorerScale(observation: ReplayObservationApi): {
    min: number
    max: number | null
    label: string | null
} {
    const scale = (configFromSnapshot(observation.scanner_snapshot) as ScorerScannerConfig | null)?.scale
    return {
        min: typeof scale?.min === 'number' ? scale.min : 0,
        max: typeof scale?.max === 'number' ? scale.max : null,
        label: scale?.label ?? null,
    }
}

/** Red at the bad end of the scale through amber to green at the good end. */
function scoreColor(score: number, min: number, max: number, highIs: Direction): string {
    const fromMin = max > min ? Math.min(1, Math.max(0, (score - min) / (max - min))) : 1
    const position = highIs === 'good' ? fromMin : 1 - fromMin
    return position < 0.5
        ? `color-mix(in oklab, var(--warning) ${Math.round(position * 200)}%, var(--danger))`
        : `color-mix(in oklab, var(--success) ${Math.round((position - 0.5) * 200)}%, var(--warning))`
}

/** The verdict's text color, given whether the scanner's question is good or bad news. */
export function verdictClassFor(observation: ReplayObservationApi, verdict: MonitorVerdict): string {
    return verdictClass(verdict, direction(observation.prompt_valence))
}

/** The score's color on the scanner's scale, or null when the scale or the question's valence is unknown. */
export function scoreColorFor(observation: ReplayObservationApi, score: number): string | null {
    const { min, max } = scorerScale(observation)
    const highIs = direction(observation.prompt_valence)
    return max !== null && highIs ? scoreColor(score, min, max, highIs) : null
}
