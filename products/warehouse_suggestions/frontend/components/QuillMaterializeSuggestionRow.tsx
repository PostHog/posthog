import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { suggestionBlockedReason } from '../suggestionBlockedReason'
import { isMaterializePayload, materializeHighlight, readSummary, rebuiltSummary } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { MaterializeSuggestionRowProps } from './MaterializeSuggestionRow'
import { QuillDismissSuggestionButtons } from './QuillDismissSuggestionButtons'
import { QuillSuggestionRow } from './QuillSuggestionRow'
import { QuillSuggestionSubjectLink } from './QuillSuggestionSubjectLink'
import { QuillWhyThisSuggestion } from './QuillWhyThisSuggestion'

export function QuillMaterializeSuggestionRow({
    suggestion,
    windowDays,
}: MaterializeSuggestionRowProps): JSX.Element | null {
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const { openMaterializeModal } = useActions(warehouseSuggestionsLogic)
    const { payload } = suggestion
    if (!isMaterializePayload(payload)) {
        return null
    }
    const leaving = leavingSuggestionIds.includes(suggestion.id)
    const rebuiltByViews = payload.recomputed_by_views ?? 0
    const readByPeople = (suggestion.evidence.human_requests ?? 0) > 0
    const blockedReason = suggestionBlockedReason(suggestion, actionsInFlight, leaving)

    return (
        <QuillSuggestionRow
            suggestionId={suggestion.id}
            assignee={suggestion.assignee}
            canAct={suggestion.can_act}
            leaving={leaving}
            icon={iconForType('data_modeling')}
            title={<QuillSuggestionSubjectLink suggestion={suggestion} />}
            meta={[
                rebuiltByViews > 0 && <span key="rebuilt">{rebuiltSummary(rebuiltByViews)}</span>,
                (readByPeople || rebuiltByViews === 0) && (
                    <QuillWhyThisSuggestion
                        key="reads"
                        evidence={suggestion.evidence}
                        windowDays={windowDays}
                        label={readSummary(suggestion.evidence)}
                    />
                ),
            ].filter(Boolean)}
            highlight={materializeHighlight(payload)}
            actions={
                <>
                    <Button
                        variant="outline"
                        size="icon"
                        aria-label="Materialize"
                        tooltip="Materialize"
                        disabledReason={blockedReason}
                        onClick={() => openMaterializeModal(suggestion.id)}
                        data-attr="warehouse-suggestions-materialize"
                    >
                        <IconCheck />
                    </Button>
                    <QuillDismissSuggestionButtons
                        suggestionId={suggestion.id}
                        kind={suggestion.kind}
                        disabledReason={blockedReason}
                    />
                </>
            }
        />
    )
}
