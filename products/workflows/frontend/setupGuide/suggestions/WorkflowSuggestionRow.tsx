import { useActions, useValues } from 'kea'

import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { SuggestionCard } from './suggestionCards'
import { WorkflowDataSuggestionsSurface, workflowDataSuggestionsLogic } from './workflowDataSuggestionsLogic'

/** A one-line suggestion, for the suggestions under the top one. */
export function WorkflowSuggestionRow({
    card,
    surface,
}: {
    card: SuggestionCard
    surface: WorkflowDataSuggestionsSurface
}): JSX.Element {
    const logic = workflowDataSuggestionsLogic({ surface })
    const { buildingKey } = useValues(logic)
    const { startSuggestion } = useActions(logic)
    const building = buildingKey === card.key

    return (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded border px-3 py-2">
            <div className="flex min-w-0 flex-col">
                <Tooltip title={card.description}>
                    <span className="truncate font-semibold">{card.title}</span>
                </Tooltip>
                <span className="inline-flex min-w-0 items-center gap-1 text-xs text-secondary">
                    <code className="truncate text-primary">{card.triggerEvent}</code>
                    <span translate="no">{humanFriendlyNumber(card.weeklyCount)}</span>
                    <span>this week</span>
                </span>
            </div>
            <LemonButton
                type="secondary"
                size="small"
                loading={building}
                disabledReason={buildingKey && !building ? 'Another workflow is being built' : undefined}
                onClick={() => startSuggestion(card)}
                // pinned: data-attr - autocapture dashboards read it
                data-attr="workflows-data-suggestion-ai"
            >
                {building ? 'Building your workflow' : 'Create workflow'}
            </LemonButton>
        </div>
    )
}
