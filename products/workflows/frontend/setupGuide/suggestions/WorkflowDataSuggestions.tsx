import { useValues } from 'kea'

import { workflowDataSuggestionsLogic } from './workflowDataSuggestionsLogic'
import { WorkflowSuggestionCard } from './WorkflowSuggestionCard'

export function WorkflowDataSuggestions(): JSX.Element | null {
    const { cards } = useValues(workflowDataSuggestionsLogic({ surface: 'empty_state' }))

    if (cards.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-2" data-attr="workflows-data-suggestions">
            <div className="flex items-center gap-3">
                <div className="h-px flex-1 bg-border-primary" />
                <span className="text-xs text-tertiary">Or start from your data</span>
                <div className="h-px flex-1 bg-border-primary" />
            </div>
            {cards.map((card) => (
                <WorkflowSuggestionCard key={card.key} card={card} surface="empty_state" />
            ))}
        </div>
    )
}
