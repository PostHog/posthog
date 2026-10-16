import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import type { ConversionRecommendationApi } from '../generated/api.schemas'

export function ConversionRecommendationCard({
    recommendation,
    disabledReason,
    onReview,
}: {
    recommendation: ConversionRecommendationApi
    disabledReason?: string
    onReview: () => void
}): JSX.Element {
    return (
        <LemonCard className="space-y-3 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
                <h4 className="mb-0 break-words">{recommendation.name}</h4>
                <LemonTag>
                    {recommendation.state === 'needs_decision' ? 'Needs your review' : 'Needs a preview'}
                </LemonTag>
            </div>
            <p className="mb-0 break-words">{recommendation.reason}</p>
            <p className="mb-0 text-secondary break-words">
                {recommendation.candidate.kind === 'ActionsNode' ? 'Action' : 'Event'}: {recommendation.candidate.name}
                {recommendation.candidate.count != null && (
                    <> · {recommendation.candidate.count.toLocaleString()} events in the analysis period</>
                )}
            </p>
            {recommendation.questions.length > 0 && (
                <ul className="pl-5 mb-0 space-y-1">
                    {recommendation.questions.map((question, index) => (
                        <li className="break-words" key={index}>
                            {question}
                        </li>
                    ))}
                </ul>
            )}
            {recommendation.draft ? (
                <LemonButton
                    type="secondary"
                    disabledReason={disabledReason}
                    onClick={onReview}
                    data-attr="marketing-conversion-review-candidate"
                >
                    Review and preview
                </LemonButton>
            ) : (
                <p className="mb-0 text-secondary">
                    Resolve the missing source mapping with PostHog AI, or configure the goal manually below.
                </p>
            )}
        </LemonCard>
    )
}
