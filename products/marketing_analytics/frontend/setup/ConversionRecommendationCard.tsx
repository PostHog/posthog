import { LemonButton, LemonCollapse, LemonTag } from '@posthog/lemon-ui'

import type { ConversionRecommendationApi } from '../generated/api.schemas'

export function ConversionRecommendationCard({
    recommendation,
    onUseSuggestion,
    onDismiss,
    disabledReason,
}: {
    recommendation: ConversionRecommendationApi
    onUseSuggestion: () => void
    onDismiss?: () => void
    disabledReason?: string | null
}): JSX.Element {
    return (
        <div className="flex flex-wrap items-start gap-2 py-2 min-w-0">
            <LemonCollapse
                embedded
                size="small"
                className="flex-1 min-w-0 basis-64"
                panels={[
                    {
                        key: recommendation.source_ref,
                        header: {
                            className: 'py-1',
                            children: (
                                <div className="min-w-0 text-left">
                                    <div className="flex flex-wrap items-center gap-2">
                                        <strong className="break-words">{recommendation.name}</strong>
                                        <LemonTag size="small">
                                            {recommendation.intent === 'revenue'
                                                ? 'Potential revenue goal'
                                                : recommendation.intent === 'customer'
                                                  ? 'Potential customer goal'
                                                  : 'Potential conversion goal'}
                                        </LemonTag>
                                    </div>
                                    <div className="text-secondary text-xs font-normal break-all mt-1">
                                        <span>{recommendation.candidate.name}</span>
                                        {recommendation.candidate.count != null && (
                                            <span>{` · ${recommendation.candidate.count.toLocaleString()} events`}</span>
                                        )}
                                    </div>
                                </div>
                            ),
                        },
                        content: (
                            <div className="space-y-2 text-sm break-words">
                                <p className="mb-0">{recommendation.reason}</p>
                                {recommendation.amount_property && (
                                    <p className="mb-0 text-secondary">{`Amount property: ${recommendation.amount_property}`}</p>
                                )}
                                {recommendation.questions.length > 0 && (
                                    <ul className="pl-5 mb-0 space-y-1">
                                        {recommendation.questions.map((question, index) => (
                                            <li key={index}>{question}</li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        ),
                    },
                ]}
            />
            <div className="flex flex-wrap items-center gap-1 mt-1 ml-auto">
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onUseSuggestion}
                    disabledReason={disabledReason}
                    data-attr="marketing-conversion-use-suggestion"
                >
                    Review suggestion
                </LemonButton>
                {onDismiss && (
                    <LemonButton size="small" onClick={onDismiss} data-attr="marketing-conversion-dismiss-suggestion">
                        Dismiss
                    </LemonButton>
                )}
            </div>
        </div>
    )
}
