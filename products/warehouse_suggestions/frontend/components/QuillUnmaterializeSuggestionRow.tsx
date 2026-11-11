import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { suggestionBlockedReason } from '../suggestionBlockedReason'
import { isUnmaterializePayload, readSummary, unmaterializeHighlight } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillDismissSuggestionButtons } from './QuillDismissSuggestionButtons'
import { QuillRowSelectionProps, QuillSuggestionRow } from './QuillSuggestionRow'
import { QuillSuggestionSubjectLink } from './QuillSuggestionSubjectLink'
import { QuillWhyThisSuggestion } from './QuillWhyThisSuggestion'
import { UnmaterializeSuggestionRowProps } from './UnmaterializeSuggestionRow'

export function QuillUnmaterializeSuggestionRow({
    suggestion,
    windowDays,
    selection,
}: UnmaterializeSuggestionRowProps & QuillRowSelectionProps): JSX.Element | null {
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const { openAcceptConfirm } = useActions(warehouseSuggestionsLogic)
    const { payload } = suggestion
    if (!isUnmaterializePayload(payload)) {
        return null
    }
    const leaving = leavingSuggestionIds.includes(suggestion.id)
    const blockedReason = suggestionBlockedReason(suggestion, actionsInFlight, leaving)

    return (
        <QuillSuggestionRow
            suggestionId={suggestion.id}
            selection={selection}
            assignee={suggestion.assignee}
            canAct={suggestion.can_act}
            leaving={leaving}
            icon={iconForType('data_modeling')}
            title={<QuillSuggestionSubjectLink suggestion={suggestion} />}
            meta={[
                <QuillWhyThisSuggestion
                    key="reads"
                    evidence={suggestion.evidence}
                    windowDays={windowDays}
                    label={readSummary(suggestion.evidence)}
                />,
            ]}
            highlight={unmaterializeHighlight(payload)}
            actions={
                <>
                    <Button
                        variant="outline"
                        size="icon"
                        aria-label="Stop materializing"
                        tooltip="Stop materializing"
                        disabledReason={blockedReason}
                        onClick={() => openAcceptConfirm(suggestion.id)}
                        data-attr="warehouse-suggestions-unmaterialize"
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
