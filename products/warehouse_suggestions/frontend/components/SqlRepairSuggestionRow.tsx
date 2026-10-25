import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import type { WarehouseSuggestionApi } from '../generated/api.schemas'
import { isSqlRepairPayload } from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { DismissSuggestionMenu } from './DismissSuggestionMenu'
import { SuggestionRow } from './SuggestionRow'
import { SuggestionSubjectLink } from './SuggestionSubjectLink'

const EDIT_ACCESS_REASON = 'You need edit access to this view'

export interface SqlRepairSuggestionRowProps {
    suggestion: WarehouseSuggestionApi
}

export function SqlRepairSuggestionRow({ suggestion }: SqlRepairSuggestionRowProps): JSX.Element | null {
    const { actionsInFlight, leavingSuggestionIds } = useValues(warehouseSuggestionsLogic)
    const { openAcceptConfirm } = useActions(warehouseSuggestionsLogic)
    const { payload } = suggestion
    if (!isSqlRepairPayload(payload)) {
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
            meta={[<span key="reason">{payload.reason}</span>]}
            actions={
                <>
                    <LemonButton
                        size="small"
                        type="secondary"
                        disabledReason={blockedReason}
                        onClick={() => openAcceptConfirm(suggestion.id)}
                        data-attr="warehouse-suggestions-sql-repair"
                    >
                        Review repair
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
