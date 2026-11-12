import type { ExperimentConclusionApi } from '@/api/experiments'
import type { ThemeColors } from '@/ui/theme'

/** The web's `ExperimentConclusion` values, in the order its select lists them. */
export const CONCLUSIONS: readonly ExperimentConclusionApi[] = [
    'won',
    'lost',
    'inconclusive',
    'stopped_early',
    'invalid',
]

export interface ConclusionCopy {
    label: string
    /** The web's `CONCLUSION_DISPLAY_CONFIG` description, shortened for a phone. */
    description: string
}

export const CONCLUSION_COPY: Record<ExperimentConclusionApi, ConclusionCopy> = {
    won: { label: 'Won', description: 'A variant beat control, and the result is significant.' },
    lost: { label: 'Lost', description: 'The variants did worse than control, and the result is significant.' },
    inconclusive: { label: 'Inconclusive', description: 'No significant difference between the variants and control.' },
    stopped_early: { label: 'Stopped early', description: 'Ended before it reached a clear result.' },
    invalid: {
        label: 'Invalid',
        description: 'The data is not reliable, for example because of tracking errors or a broken setup.',
    },
}

/** The dot next to a conclusion, the same hues as the web's `bg-success`, `bg-danger` and `bg-warning`. */
export function conclusionColor(conclusion: ExperimentConclusionApi, colors: ThemeColors): string {
    switch (conclusion) {
        case 'won':
            return colors.diffGreen
        case 'lost':
            return colors.diffRed
        case 'inconclusive':
            return colors.yellow
        default:
            return colors.tertiary
    }
}

export function isConclusion(value: unknown): value is ExperimentConclusionApi {
    return typeof value === 'string' && (CONCLUSIONS as readonly string[]).includes(value)
}
