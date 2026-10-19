import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import type { ConversionRecommendationApi } from '../generated/api.schemas'

export function ConversionRecommendationCard({
    recommendation,
    onUseSuggestion,
    alreadyConfigured = false,
    disabledReason,
}: {
    recommendation: ConversionRecommendationApi
    onUseSuggestion: () => void
    alreadyConfigured?: boolean
    disabledReason?: string | null
}): JSX.Element {
    return (
        <LemonCard className="space-y-3 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
                <h4 className="mb-0 break-words">{recommendation.name}</h4>
                <LemonTag>
                    {recommendation.intent === 'revenue'
                        ? 'Potential revenue goal'
                        : recommendation.intent === 'customer'
                          ? 'Potential customer goal'
                          : 'Potential conversion goal'}
                </LemonTag>
                {alreadyConfigured && <LemonTag type="success">Already configured</LemonTag>}
            </div>
            <p className="mb-0 break-words">{recommendation.reason}</p>
            <p className="mb-0 text-secondary break-words">
                <span>
                    {`${recommendation.candidate.kind === 'ActionsNode' ? 'Action' : 'Event'}: ${recommendation.candidate.name}`}
                </span>
                {recommendation.candidate.count != null && (
                    <span>{` · ${recommendation.candidate.count.toLocaleString()} events in the analysis period`}</span>
                )}
            </p>
            {recommendation.amount_property && (
                <p className="mb-0 text-secondary break-words">{`Amount property: ${recommendation.amount_property}`}</p>
            )}
            {recommendation.questions.length > 0 && (
                <ul className="pl-5 mb-0 space-y-1">
                    {recommendation.questions.map((question, index) => (
                        <li className="break-words" key={index}>
                            {question}
                        </li>
                    ))}
                </ul>
            )}
            <LemonButton
                type="secondary"
                onClick={onUseSuggestion}
                disabledReason={disabledReason}
                data-attr="marketing-conversion-use-suggestion"
            >
                {alreadyConfigured ? 'Review goal' : 'Use suggestion'}
            </LemonButton>
        </LemonCard>
    )
}
