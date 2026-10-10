import { useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { workflowDataSuggestionsLogic } from './workflowDataSuggestionsLogic'
import { WorkflowSuggestionCard } from './WorkflowSuggestionCard'

const LOADING_CARD_COUNT = 3

export function WorkflowDataSuggestions(): JSX.Element | null {
    const { cards, aiResultLoading } = useValues(workflowDataSuggestionsLogic({ surface: 'empty_state' }))

    // Suggestions are optional: a failed or empty run shows nothing, not even the divider.
    if (!aiResultLoading && cards.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2" data-attr="workflows-data-suggestions">
            <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-border-primary" />
                <span className="inline-flex items-center gap-1 text-xs text-tertiary">
                    {aiResultLoading ? <Spinner className="size-3" /> : <IconSparkles className="size-3" />}
                    Or start from your data
                </span>
                <div className="h-px flex-1 bg-border-primary" />
            </div>
            {aiResultLoading ? (
                <>
                    <span className="text-center text-xs text-secondary">
                        Suggesting workflows based on the events your project sends
                    </span>
                    {Array.from({ length: LOADING_CARD_COUNT }, (_, index) => (
                        <LemonSkeleton key={index} className="h-40 rounded" />
                    ))}
                </>
            ) : (
                cards.map((card) => <WorkflowSuggestionCard key={card.key} card={card} surface="empty_state" />)
            )}
        </div>
    )
}
