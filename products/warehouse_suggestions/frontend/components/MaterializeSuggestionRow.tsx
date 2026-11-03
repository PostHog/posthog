import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import {
    isMaterializePayload,
    materializeSaving,
    readSummary,
    rebuiltSummary,
    savingHighlight,
} from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionButtons } from './DismissSuggestionButtons'
import { SuggestionRow } from './SuggestionRow'
import { SuggestionSubjectLink } from './SuggestionSubjectLink'
import { WhyThisSuggestion } from './WhyThisSuggestion'

const EDIT_ACCESS_REASON = 'You need edit access to this view'

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
    const rebuiltByViews = payload.recomputed_by_views ?? 0
    const readByPeople = (suggestion.evidence.human_requests ?? 0) > 0
    const blockedReason = !suggestion.can_act
        ? EDIT_ACCESS_REASON
        : actionsInFlight[suggestion.id] || leaving
          ? 'Working'
          : undefined

    return (
        <SuggestionRow
            suggestionId={suggestion.id}
            assignee={suggestion.assignee}
            canAct={suggestion.can_act}
            leaving={leaving}
            icon={iconForType('data_modeling')}
            title={<SuggestionSubjectLink suggestion={suggestion} />}
            meta={[
                rebuiltByViews > 0 && <span key="rebuilt">{rebuiltSummary(rebuiltByViews)}</span>,
                (readByPeople || rebuiltByViews === 0) && (
                    <WhyThisSuggestion
                        key="reads"
                        evidence={suggestion.evidence}
                        windowDays={windowDays}
                        label={readSummary(suggestion.evidence)}
                    />
                ),
            ].filter(Boolean)}
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
