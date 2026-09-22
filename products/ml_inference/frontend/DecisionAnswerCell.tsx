import { LemonTag } from '@posthog/lemon-ui'

import type { DecisionAnswerApi } from './generated/api.schemas'

function percent(value: number | null | undefined): string {
    return value === null || value === undefined ? '' : `${Math.round(value * 100)}%`
}

export function DecisionAnswerCell({ answer }: { answer: DecisionAnswerApi }): JSX.Element {
    if (answer.type === 'noul') {
        const yes = answer.probability ?? 0
        return (
            <div className="flex items-center gap-2">
                <LemonTag type={yes >= 0.5 ? 'success' : 'danger'}>{yes >= 0.5 ? 'Yes' : 'No'}</LemonTag>
                <span className="text-secondary">{percent(yes)} yes</span>
            </div>
        )
    }
    const ranked = Object.entries(answer.probabilities ?? {}).sort(([, a], [, b]) => b - a)
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
                <LemonTag type="highlight">
                    {answer.type === 'choice' ? answer.choice : answer.score?.toFixed(2)}
                </LemonTag>
                <span className="text-secondary">{percent(answer.confidence)} confidence</span>
            </div>
            <div className="text-secondary text-xs">
                {ranked.map(([option, probability]) => `${option} ${percent(probability)}`).join(' · ')}
            </div>
        </div>
    )
}
