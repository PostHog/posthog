import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { suggestionBlockedReason } from '../suggestionBlockedReason'
import { isMaterializePayload, materializeSaving, readSummary, savingHighlight } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionButtons } from './DismissSuggestionButtons'
import { SuggestionRow } from './SuggestionRow'
import { SuggestionSubjectLink } from './SuggestionSubjectLink'
import { WhyThisSuggestion } from './WhyThisSuggestion'

export interface MaterializeSuggestionRowProps {
    suggestion: WarehouseSuggestionApi
    windowDays: number
}

export function MaterializeSuggestionRow({
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
    const blockedReason = suggestionBlockedReason(suggestion, actionsInFlight, leaving)

    return (
        <SuggestionRow
            suggestionId={suggestion.id}
            assignee={suggestion.assignee}
            canAct={suggestion.can_act}
            leaving={leaving}
            icon={iconForType('data_modeling')}
            title={<SuggestionSubjectLink suggestion={suggestion} />}
            meta={[
                <WhyThisSuggestion
                    key="reads"
                    evidence={suggestion.evidence}
                    windowDays={windowDays}
                    label={readSummary(suggestion.evidence)}
                />,
            ]}
            highlight={savingHighlight(materializeSaving(payload))}
            actions={
                <>
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconCheck />}
                        tooltip="Materialize"
                        disabledReason={blockedReason}
                        onClick={() => openMaterializeModal(suggestion.id)}
                        data-attr="warehouse-suggestions-materialize"
                    />
                    <DismissSuggestionButtons
                        suggestionId={suggestion.id}
                        kind={suggestion.kind}
                        disabledReason={blockedReason}
                    />
                </>
            }
        />
    )
}
