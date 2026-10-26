import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import {
    isUnmaterializePayload,
    readSummary,
    readTimeLabel,
    savingHighlight,
    unmaterializeSaving,
} from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionMenu } from './DismissSuggestionMenu'
import { SuggestionRow } from './SuggestionRow'
import { SuggestionSubjectLink } from './SuggestionSubjectLink'
import { WhyThisSuggestion } from './WhyThisSuggestion'

const EDIT_ACCESS_REASON = 'You need edit access to this view'

export interface UnmaterializeSuggestionRowProps {
    suggestion: WarehouseSuggestionApi
    windowDays: number
}

export function UnmaterializeSuggestionRow({
    suggestion,
    windowDays,
}: UnmaterializeSuggestionRowProps): JSX.Element | null {
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const { openAcceptConfirm } = useActions(warehouseSuggestionsLogic)
    const { payload } = suggestion
    if (!isUnmaterializePayload(payload)) {
        return null
    }
    const leaving = leavingSuggestionIds.includes(suggestion.id)
    const blockedReason = !suggestion.can_act
        ? EDIT_ACCESS_REASON
        : actionsInFlight[suggestion.id] || leaving
          ? 'Working'
          : undefined

    return (
        <SuggestionRow
            suggestionId={suggestion.id}
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
                <span key="read-time">{readTimeLabel(payload.read_seconds)}</span>,
            ]}
            highlight={savingHighlight(unmaterializeSaving(payload))}
            actions={
                <>
                    <LemonButton
                        size="small"
                        type="secondary"
                        disabledReason={blockedReason}
                        onClick={() => openAcceptConfirm(suggestion.id)}
                        data-attr="warehouse-suggestions-unmaterialize"
                    >
                        Stop materializing
                    </LemonButton>
                    <DismissSuggestionMenu
                        suggestionId={suggestion.id}
                        kind={suggestion.kind}
                        disabledReason={blockedReason}
                    />
                </>
            }
        />
    )
}
