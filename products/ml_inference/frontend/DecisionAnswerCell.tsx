import { LemonTag } from '@posthog/lemon-ui'

import type { DecisionAnswerApi } from './generated/api.schemas'

function percent(value: number | null | undefined): string {
    return value === null || value === undefined ? '' : `${Math.round(value * 100)}%`
}

export function DecisionAnswerCell({
    answer,
    scaleLabels,
}: {
    answer: DecisionAnswerApi
    /** For a score answer, the label of each scale point in order, so probabilities read as words rather than indexes. */
    scaleLabels?: string[]
}): JSX.Element {
    if (answer.type === 'noul') {
        const yes = answer.probability ?? 0
        return (
            <div className="flex items-center gap-2">
                <LemonTag type={yes >= 0.5 ? 'success' : 'danger'}>{yes >= 0.5 ? 'Yes' : 'No'}</LemonTag>
                <span className="text-secondary">{percent(yes)} yes</span>
            </div>
        )
    }
    const labelOf = (option: string): string => scaleLabels?.[Number(option)] ?? option
    const ranked = Object.entries(answer.probabilities ?? {}).sort(([, a], [, b]) => b - a)
    const score = answer.score ?? 0
    const scaleTop = ranked.length - 1
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <LemonTag type="highlight">
                    {answer.type === 'choice' ? answer.choice : labelOf(String(Math.round(score)))}
                </LemonTag>
                {answer.type === 'score' && (
                    <span className="text-secondary">
                        {score.toFixed(2)} on a 0 to {scaleTop} scale
                    </span>
                )}
                <span className="text-secondary">{percent(answer.confidence)} confidence</span>
            </div>
            <div className="text-secondary text-xs">
                {ranked.map(([option, probability]) => `${labelOf(option)} ${percent(probability)}`).join(' · ')}
            </div>
        </div>
    )
}
